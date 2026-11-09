# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""History of the Upload file checks, saved in the DWH.

Two kinds of tables on the "DWH_APP Oracle" connection (created by the DBA, see
docs/upload_file_dwh_tables.sql, the application only reads and writes rows):

* ``UPLOAD_FILE_HISTORY``: one row per use of the feature, successful or not;
* one detail table per service (e.g. ``UPLOAD_FILE_VPG_RESULT_DETAIL``): one row
  per row of the output, joined on ``HISTORY_ID = UPLOAD_FILE_HISTORY.ID``.

A check and its detail rows are written in one transaction. The output file of a
successful check is rebuilt from its detail rows. Nothing is ever deleted.
Dates are stored in Vietnam time.
"""

import logging
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import (
    and_,
    Column,
    DateTime,
    func,
    Integer,
    LargeBinary,
    MetaData,
    select,
    String,
    Table,
)

from superset.upload_file.db import dwh_connection, DWH_SCHEMA
from superset.upload_file.handlers import get_handler
from superset.upload_file.handlers.base import BusinessHandler, ProcessResult

logger = logging.getLogger(__name__)

PAGE_SIZE = 10
VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DISPLAY_FORMAT = "%d/%m/%Y %H:%M:%S"
MAX_MESSAGE_LENGTH = 2000

# Stored in upper case (as in the DDL); the API and the page use lower case
STATUS_SUCCESS = "SUCCESS"
STATUS_FAIL = "FAIL"

_metadata = MetaData()
history_table = Table(
    "upload_file_history",
    _metadata,
    Column("id", Integer, primary_key=True),
    Column("service", String(64), nullable=False),
    Column("user_id", Integer),
    Column("username", String(256)),
    Column("checked_at", DateTime, nullable=False),  # Vietnam time
    Column("status", String(16), nullable=False),
    Column("fail_message", String(MAX_MESSAGE_LENGTH)),
    Column("file_name", String(256)),
    # Legacy: the output is rebuilt from the detail rows, so it stays empty
    Column("result_data", LargeBinary),
    Column("ts_count", Integer),
    Column("ta_count", Integer),
    Column("tf_count", Integer),
    Column("duration_ms", Integer),
    schema=DWH_SCHEMA,
)

SORTABLE_COLUMNS = {
    "service": history_table.c.service,
    "user": history_table.c.username,
    "check_date": history_table.c.checked_at,
    "status": history_table.c.status,
    "fail_message": history_table.c.fail_message,
    "file_name": history_table.c.file_name,
    "ts": history_table.c.ts_count,
    "ta": history_table.c.ta_count,
    "tf": history_table.c.tf_count,
    "duration": history_table.c.duration_ms,
}
DEFAULT_ORDER = "check_date"


def _now() -> datetime:
    """Current Vietnam time, without time zone (how it is stored)."""
    return datetime.now(VIETNAM_TZ).replace(tzinfo=None)


def result_file_name(file_name: Optional[str], checked_at: datetime) -> str:
    """Name of the file returned for a check, without extension.

    ``<uploaded name>_result_<ddmmyyyy>``, the date being the check date
    (e.g. ``log_result_04112026``).
    """
    base = (file_name or "result").rsplit(".", 1)[0]
    return f"{base}_result_{checked_at:%d%m%Y}"


def _insert_returning_id(connection: Any, values: dict[str, Any]) -> int:
    statement = history_table.insert().values(**values)
    if connection.dialect.implicit_returning:  # Oracle, PostgreSQL
        return int(connection.execute(statement.returning(history_table.c.id)).scalar())
    return int(connection.execute(statement).inserted_primary_key[0])


def add_entry(
    *,
    handler: BusinessHandler,
    user_id: Optional[int],
    username: Optional[str],
    file_name: str,
    result: Optional[ProcessResult] = None,
    fail_message: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> int:
    """Record one check (and the rows of its output) and return its id."""
    values = {
        "service": handler.label,
        "user_id": user_id,
        "username": (username or "")[:256] or None,
        "checked_at": _now(),
        "status": STATUS_SUCCESS if result is not None else STATUS_FAIL,
        "fail_message": (fail_message or "")[:MAX_MESSAGE_LENGTH] or None,
        "file_name": file_name[:256],
        "ts_count": result.summary.get("TS", 0) if result is not None else None,
        "ta_count": result.summary.get("TA", 0) if result is not None else None,
        "tf_count": result.summary.get("TF", 0) if result is not None else None,
        "duration_ms": duration_ms,
    }
    with dwh_connection(write=True) as connection:
        entry_id = _insert_returning_id(connection, values)
        if result is not None and result.records:
            connection.execute(
                handler.detail_table.insert(),
                [{**record, "history_id": entry_id} for record in result.records],
            )
    return entry_id


def _like_pattern(text: str) -> str:
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _filters(
    service: Optional[str],
    user: Optional[str],
    status: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
    file_name: Optional[str],
) -> list[Any]:
    conditions: list[Any] = []
    if service:
        conditions.append(history_table.c.service == service)
    if user:
        conditions.append(
            func.lower(history_table.c.username).like(_like_pattern(user), escape="\\")
        )
    if file_name:
        conditions.append(
            func.lower(history_table.c.file_name).like(
                _like_pattern(file_name), escape="\\"
            )
        )
    if status and status.upper() in (STATUS_SUCCESS, STATUS_FAIL):
        conditions.append(history_table.c.status == status.upper())
    # "Check Date" is picked as days (Vietnam time); both ends are included
    if date_from:
        conditions.append(history_table.c.checked_at >= datetime.combine(date_from, time.min))
    if date_to:
        conditions.append(
            history_table.c.checked_at
            < datetime.combine(date_to + timedelta(days=1), time.min)
        )
    return conditions


def list_entries(
    page: int,
    order_column: str,
    descending: bool,
    *,
    service: Optional[str] = None,
    user: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    file_name: Optional[str] = None,
) -> tuple[int, list[dict[str, Any]]]:
    """One page of the (filtered) history, newest first by default."""
    where = and_(*_filters(service, user, status, date_from, date_to, file_name))
    column = SORTABLE_COLUMNS.get(order_column, SORTABLE_COLUMNS[DEFAULT_ORDER])
    order = column.desc() if descending else column.asc()
    with dwh_connection() as connection:
        total = connection.execute(
            select(func.count()).select_from(history_table).where(where)
        ).scalar()
        rows = connection.execute(
            select(
                history_table.c.id,
                history_table.c.service,
                history_table.c.username,
                history_table.c.checked_at,
                history_table.c.status,
                history_table.c.fail_message,
                history_table.c.file_name,
                history_table.c.ts_count,
                history_table.c.ta_count,
                history_table.c.tf_count,
                history_table.c.duration_ms,
            )
            .where(where)
            .order_by(order, history_table.c.id.desc())
            .limit(PAGE_SIZE)
            .offset((max(page, 1) - 1) * PAGE_SIZE)
        ).all()
    entries = []
    for row in rows:
        success = row.status == STATUS_SUCCESS
        entries.append(
            {
                "id": int(row.id),
                "service": row.service,
                "user": row.username or "",
                "check_date": row.checked_at.strftime(DISPLAY_FORMAT),
                "status": "success" if success else "fail",
                "fail_message": row.fail_message or "",
                "file_name": row.file_name or "",
                "result_file_name": (
                    result_file_name(row.file_name, row.checked_at) if success else ""
                ),
                "ts": _int_or_none(row.ts_count),
                "ta": _int_or_none(row.ta_count),
                "tf": _int_or_none(row.tf_count),
                # seconds, 1 decimal
                "duration": (
                    round(float(row.duration_ms) / 1000, 1)
                    if row.duration_ms is not None
                    else None
                ),
                "can_download": success,
            }
        )
    return int(total or 0), entries


def _int_or_none(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


def get_result(entry_id: int) -> Optional[tuple[str, ProcessResult]]:
    """The output of a successful check, rebuilt from its saved rows."""
    with dwh_connection() as connection:
        head = connection.execute(
            select(
                history_table.c.service,
                history_table.c.file_name,
                history_table.c.checked_at,
                history_table.c.status,
                history_table.c.ts_count,
                history_table.c.ta_count,
                history_table.c.tf_count,
            ).where(history_table.c.id == entry_id)
        ).first()
        if head is None or head.status != STATUS_SUCCESS:
            return None
        handler = get_handler(head.service)
        if handler is None:
            return None
        detail = handler.detail_table
        records = [
            dict(row)
            for row in connection.execute(
                select(detail)
                .where(detail.c.history_id == entry_id)
                .order_by(detail.c.detail_id)
            )
            .mappings()
            .all()
        ]
    result = handler.result_from_records(records)
    result.summary = {
        "TS": _int_or_none(head.ts_count) or 0,
        "TA": _int_or_none(head.ta_count) or 0,
        "TF": _int_or_none(head.tf_count) or 0,
    }
    return result_file_name(head.file_name, head.checked_at), result
