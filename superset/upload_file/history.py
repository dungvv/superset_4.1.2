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
    MetaData,
    Numeric,
    or_,
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
MAX_PARTNER_LENGTH = 512

# Stored in upper case (as in the DDL); the API and the page use lower case.
# A failed check says where it failed:
STATUS_SUCCESS = "SUCCESS"
STATUS_FAIL_UPLOAD = "FAIL_UPLOAD"  # the file was refused (type, size, template, data)
STATUS_FAIL_PROCESS = "FAIL_PROCESS"  # valid file, but the processing failed (DWH...)
STATUS_FAIL_LEGACY = "FAIL"  # rows written before the two kinds existed

_metadata = MetaData()
history_table = Table(
    "upload_file_history",
    _metadata,
    Column("id", Integer, primary_key=True),
    Column("service", String(64), nullable=False),
    Column("user_id", Integer),
    Column("user_name", String(256)),
    # Vietnam time, to the second (Oracle DATE)
    Column("checked_at", DateTime, nullable=False),
    Column("status", String(16), nullable=False),
    Column("fail_message", String(MAX_MESSAGE_LENGTH)),
    Column("file_name", String(256)),
    # Partners of the check, "BCEL,SOKXAY" (second part of CUSTOMER_NAME)
    Column("partner_name", String(MAX_PARTNER_LENGTH)),
    Column("total_txn", Integer),  # number of transactions of the file
    Column("count_txn_ts", Integer),
    Column("count_txn_ta", Integer),
    Column("count_txn_tf", Integer),
    # processing time of the check, in seconds (1 decimal)
    Column("duration", Numeric(10, 1)),
    schema=DWH_SCHEMA,
)

SORTABLE_COLUMNS = {
    "service": history_table.c.service,
    "user": history_table.c.user_name,
    "check_date": history_table.c.checked_at,
    "status": history_table.c.status,
    "fail_message": history_table.c.fail_message,
    "file_name": history_table.c.file_name,
    "total": history_table.c.total_txn,
    "ts": history_table.c.count_txn_ts,
    "ta": history_table.c.count_txn_ta,
    "tf": history_table.c.count_txn_tf,
    "duration": history_table.c.duration,
}
DEFAULT_ORDER = "check_date"


def _now() -> datetime:
    """Current Vietnam time, without time zone (how it is stored)."""
    return datetime.now(VIETNAM_TZ).replace(tzinfo=None, microsecond=0)


def result_file_name(file_name: Optional[str], checked_at: datetime) -> str:
    """Name of the file returned for a check, without extension.

    ``<uploaded name>_result_<ddmmyyyy>``, the date being the check date
    (e.g. ``log_result_04112026``).
    """
    base = (file_name or "result").rsplit(".", 1)[0]
    return f"{base}_result_{checked_at:%d%m%Y}"


def _partner_column(result: Optional[ProcessResult]) -> Optional[str]:
    """Distinct partners of the rows of the output, "BCEL,SOKXAY"."""
    if result is None:
        return None
    names = {r.get("partner_name") for r in result.records if r.get("partner_name")}
    joined = ""
    for name in sorted(names, key=str.lower):
        candidate = f"{joined},{name}" if joined else name
        if len(candidate) > MAX_PARTNER_LENGTH:
            break  # never cut a name in the middle
        joined = candidate
    return joined or None


def _insert_returning_id(connection: Any, values: dict[str, Any]) -> int:
    statement = history_table.insert().values(**values)
    if connection.dialect.implicit_returning:  # Oracle, PostgreSQL
        return int(connection.execute(statement.returning(history_table.c.id)).scalar())
    return int(connection.execute(statement).inserted_primary_key[0])


def add_entry(
    *,
    handler: BusinessHandler,
    user_id: Optional[int],
    user_name: Optional[str],
    file_name: str,
    result: Optional[ProcessResult] = None,
    fail_message: Optional[str] = None,
    failure: str = "upload",
    total_txn: Optional[int] = None,
    duration: Optional[float] = None,
) -> int:
    """Record one check (and the rows of its output) and return its id.

    Without ``result`` the check failed: ``failure`` is ``"upload"`` when the
    file was refused, ``"process"`` when the file was valid but its processing
    failed (``total_txn`` is then the number of rows of the file).
    """
    if result is not None:
        status = STATUS_SUCCESS
        total_txn = len(result.rows)
    else:
        status = STATUS_FAIL_PROCESS if failure == "process" else STATUS_FAIL_UPLOAD
    values = {
        "service": handler.label,
        "user_id": user_id,
        "user_name": (user_name or "")[:256] or None,
        "checked_at": _now(),
        "status": status,
        "fail_message": (fail_message or "")[:MAX_MESSAGE_LENGTH] or None,
        "file_name": file_name[:256],
        "partner_name": _partner_column(result),
        "total_txn": total_txn,
        "count_txn_ts": result.summary.get("TS", 0) if result is not None else None,
        "count_txn_ta": result.summary.get("TA", 0) if result is not None else None,
        "count_txn_tf": result.summary.get("TF", 0) if result is not None else None,
        "duration": duration,
    }
    with dwh_connection(write=True) as connection:
        entry_id = _insert_returning_id(connection, values)
        if result is not None and result.records:
            connection.execute(
                handler.detail_table.insert(),
                [{**record, "history_id": entry_id} for record in result.records],
            )
    return entry_id


def _escape_like(text: str) -> str:
    return text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like_pattern(text: str) -> str:
    return f"%{_escape_like(text)}%"


def _filters(
    service: Optional[str],
    user: Optional[str],
    status: Optional[str],
    date_from: Optional[date],
    date_to: Optional[date],
    file_name: Optional[str],
    partner: Optional[str] = None,
) -> list[Any]:
    conditions: list[Any] = []
    wanted = [p.strip().lower() for p in (partner or "").split(",") if p.strip()]
    if wanted:
        # PARTNER_NAME holds the partners of the check, "BCEL,SOKXAY": keep the
        # checks that have one of the wanted partners (IN on the list)
        padded = func.lower("," + history_table.c.partner_name + ",")
        conditions.append(
            or_(
                *[
                    padded.like(f"%,{_escape_like(name)},%", escape="\\")
                    for name in wanted
                ]
            )
        )
    if service:
        conditions.append(history_table.c.service == service)
    if user:
        conditions.append(
            func.lower(history_table.c.user_name).like(_like_pattern(user), escape="\\")
        )
    if file_name:
        conditions.append(
            func.lower(history_table.c.file_name).like(
                _like_pattern(file_name), escape="\\"
            )
        )
    if status:
        wanted = {
            "SUCCESS": [STATUS_SUCCESS],
            "FAIL_UPLOAD": [STATUS_FAIL_UPLOAD, STATUS_FAIL_LEGACY],
            "FAIL_PROCESS": [STATUS_FAIL_PROCESS],
            "FAIL": [STATUS_FAIL_UPLOAD, STATUS_FAIL_PROCESS, STATUS_FAIL_LEGACY],
        }.get(status.upper())
        if wanted:
            conditions.append(history_table.c.status.in_(wanted))
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
    partner: Optional[str] = None,
) -> tuple[int, list[dict[str, Any]]]:
    """One page of the (filtered) history, newest first by default."""
    where = and_(*_filters(service, user, status, date_from, date_to, file_name, partner))
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
                history_table.c.user_name,
                history_table.c.checked_at,
                history_table.c.status,
                history_table.c.fail_message,
                history_table.c.file_name,
                history_table.c.partner_name,
                history_table.c.total_txn,
                history_table.c.count_txn_ts,
                history_table.c.count_txn_ta,
                history_table.c.count_txn_tf,
                history_table.c.duration,
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
                "user": row.user_name or "",
                "check_date": row.checked_at.strftime(DISPLAY_FORMAT),
                "status": _status_key(row.status),
                "fail_message": row.fail_message or "",
                "file_name": row.file_name or "",
                "partner_name": partner_names(row.partner_name),
                "result_file_name": (
                    result_file_name(row.file_name, row.checked_at) if success else ""
                ),
                "total": _int_or_none(row.total_txn),
                "ts": _int_or_none(row.count_txn_ts),
                "ta": _int_or_none(row.count_txn_ta),
                "tf": _int_or_none(row.count_txn_tf),
                # seconds, 1 decimal
                "duration": (
                    round(float(row.duration), 1) if row.duration is not None else None
                ),
                "can_download": success,
            }
        )
    return int(total or 0), entries


def partner_names(value: Optional[str]) -> list[str]:
    """The partners saved in the PARTNER_NAME column ("BCEL,SOKXAY")."""
    return [name for name in (value or "").split(",") if name]


def list_partners() -> list[str]:
    """Every partner name found in the history, for the filter of the page."""
    with dwh_connection() as connection:
        values = connection.execute(
            select(history_table.c.partner_name)
            .where(history_table.c.partner_name.is_not(None))
            .distinct()
        ).scalars()
        return sorted({n for v in values for n in partner_names(v)}, key=str.lower)


def _status_key(status: str) -> str:
    """Status as the API and the page name it."""
    if status == STATUS_SUCCESS:
        return "success"
    return "fail_process" if status == STATUS_FAIL_PROCESS else "fail_upload"


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
                history_table.c.count_txn_ts,
                history_table.c.count_txn_ta,
                history_table.c.count_txn_tf,
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
        "TS": _int_or_none(head.count_txn_ts) or 0,
        "TA": _int_or_none(head.count_txn_ta) or 0,
        "TF": _int_or_none(head.count_txn_tf) or 0,
    }
    return result_file_name(head.file_name, head.checked_at), result
