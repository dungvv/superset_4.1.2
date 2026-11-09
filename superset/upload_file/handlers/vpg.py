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
"""VPG business type.

Every transaction of the uploaded file is checked in two steps, both on the
"DWH_APP Oracle" connection:

* B1: the core wallet table (RPT_B1_009_026_TRANS_HISTORY__FA), matching the
  file ``transID`` with ``FIELD6``. A transaction that is not found there is a
  failed transaction (TF).
* B2: the BCCS3 table (bccs3_topup_wallet_charge_history__fa), matching the
  ``FIELD8`` found in B1 with ``trans_id``. The ``RESPONSE_CODE`` gives the
  final status (see ``decide_reply``).
"""

import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple, Optional

from sqlalchemy import Column, DateTime, Integer, MetaData, Numeric, String, Table

from superset.upload_file.db import DWH_CONNECTION, DWH_SCHEMA, query_in_chunks
from superset.upload_file.handlers.base import (
    BusinessHandler,
    ProcessError,
    ProcessResult,
)
from superset.upload_file.validator import ValidationResult

logger = logging.getLogger(__name__)

# Name of the database connection in Superset (Settings > Database Connections)
CONNECTION = DWH_CONNECTION

# Final answer of a transaction
TS = "TS"  # Transaction Success
TA = "TA"  # Transaction Abnormal (time out, to be checked by BOIT)
TF = "TF"  # Transaction Failed


class Col(NamedTuple):
    """A column of the output and of the detail table of the DWH."""

    output: str  # name in the output file, and key in the source row
    db: str  # column of UPLOAD_FILE_VPG_RESULT_DETAIL
    kind: str  # text | number | datetime
    group: str  # input | reply | core | bccs (colours of the output)
    size: int = 0  # length of a text column


# The 42 columns of the output, in order. Keep it in line with
# docs/upload_file_dwh_tables.sql. Only "date" (DATE is reserved in Oracle) and
# the BCCS "ID" (it would be confused with the join key) have another db name.
SPEC: tuple[Col, ...] = (
    # uploaded file
    Col("transID", "TRANSID", "text", "input", 64),
    Col("date", "TXN_DATE", "datetime", "input"),
    Col("Phone_NO", "PHONE_NO", "text", "input", 32),
    Col("Type", "TYPE", "text", "input", 64),
    Col("Amount", "AMOUNT", "number", "input"),
    Col("Error_code", "ERROR_CODE", "text", "input", 64),
    Col("Detail", "DETAIL", "text", "input", 1000),
    Col("Provider", "PROVIDER", "text", "input", 64),
    # final answer
    Col("Reply", "REPLY", "text", "reply", 8),
    # RPT_B1_009_026_TRANS_HISTORY__FA (B1)
    Col("FIELD6", "FIELD6", "text", "core", 64),
    Col("BUSINESS_DATE", "BUSINESS_DATE", "datetime", "core"),
    Col("TRANSFER_DATE", "TRANSFER_DATE", "datetime", "core"),
    Col("TRANSFER_ID", "TRANSFER_ID", "text", "core", 64),
    Col("SENDER_MSISDN", "SENDER_MSISDN", "text", "core", 32),
    Col("FIELD4", "FIELD4", "number", "core"),
    Col("FIELD8", "FIELD8", "text", "core", 64),
    Col("TXN_STATUS", "TXN_STATUS", "text", "core", 16),
    # ods.bccs3_topup_wallet_charge_history__fa (B2)
    Col("ID", "BCCS_ID", "text", "bccs", 64),
    Col("TRANS_ID", "TRANS_ID", "text", "bccs", 64),
    Col("REFILL_AMOUNT", "REFILL_AMOUNT", "number", "bccs"),
    Col("REFILL_DATE", "REFILL_DATE", "datetime", "bccs"),
    Col("REFILL_ISDN", "REFILL_ISDN", "text", "bccs", 32),
    Col("VAT", "VAT", "number", "bccs"),
    Col("DISCOUNT", "DISCOUNT", "number", "bccs"),
    Col("TELECOM_SERVICE_ID", "TELECOM_SERVICE_ID", "text", "bccs", 64),
    Col("PAY_TYPE", "PAY_TYPE", "text", "bccs", 64),
    Col("RESPONSE_CODE", "RESPONSE_CODE", "text", "bccs", 16),
    Col("DESCRIPTION", "DESCRIPTION", "text", "bccs", 1000),
    Col("CUSTOMER_NAME", "CUSTOMER_NAME", "text", "bccs", 256),
    Col("APP_NAME", "APP_NAME", "text", "bccs", 128),
    Col("PAYMENT_ID", "PAYMENT_ID", "text", "bccs", 64),
    Col("SALE_TRANS_ID", "SALE_TRANS_ID", "text", "bccs", 64),
    Col("ADJUST_DEBIT_TRANS_ID", "ADJUST_DEBIT_TRANS_ID", "text", "bccs", 64),
    Col("PREPAID_CODE", "PREPAID_CODE", "text", "bccs", 64),
    Col("PRODUCT_CODE", "PRODUCT_CODE", "text", "bccs", 64),
    Col("TRACE_ID", "TRACE_ID", "text", "bccs", 128),
    Col("IM_REQUEST", "IM_REQUEST", "text", "bccs", 64),
    Col("SOURCE_ISDN", "SOURCE_ISDN", "text", "bccs", 32),
    Col("TF_SOURCING_AT", "TF_SOURCING_AT", "text", "bccs", 64),
    Col("TF_ETL_AT", "TF_ETL_AT", "datetime", "bccs"),
    Col("TF_PARTITION_DATE", "TF_PARTITION_DATE", "datetime", "bccs"),
    Col("TF_SOURCE_SYSTEM", "TF_SOURCE_SYSTEM", "text", "bccs", 128),
)
OUTPUT_COLUMNS = [c.output for c in SPEC]
OUTPUT_GROUPS = [c.group for c in SPEC]
CORE_COLUMNS = tuple(c.output for c in SPEC if c.group == "core")
BCCS_COLUMNS = tuple(c.output for c in SPEC if c.group == "bccs")

_DETAIL_TYPES = {
    "text": lambda c: String(c.size),
    "number": lambda c: Numeric(),
    "datetime": lambda c: DateTime(),
}
# One row per row of the output file; the rows of a check are read back in
# detail_id order. Created by the DBA (docs/upload_file_dwh_tables.sql).
DETAIL_TABLE = Table(
    "upload_file_vpg_result_detail",
    MetaData(),
    Column("detail_id", Integer, primary_key=True),
    Column("history_id", Integer, nullable=False),
    *[Column(c.db.lower(), _DETAIL_TYPES[c.kind](c)) for c in SPEC],
    schema=DWH_SCHEMA,
)

CORE_SQL = """
    SELECT FIELD6, BUSINESS_DATE, TRANSFER_DATE, TRANSFER_ID, SENDER_MSISDN,
           FIELD4, FIELD8, TXN_STATUS
    FROM RPT_B1_009_026_TRANS_HISTORY__FA
    WHERE BUSINESS_DATE >= :date_from
      AND BUSINESS_DATE < :date_to
      AND FIELD2 IN ('SFT_BCEL_VPG')
      AND FIELD6 IN :ids
"""
BCCS_SQL = """
    SELECT *
    FROM ods.bccs3_topup_wallet_charge_history__fa
    WHERE TF_PARTITION_DATE >= :date_from
      AND TF_PARTITION_DATE < :date_to
      AND trans_id IN :ids
"""

# Formats accepted for the "date" column of the uploaded file
DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)
MAX_REPORTED_ERRORS = 5


def parse_date(value: str) -> Optional[datetime]:
    value = value.strip()
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None


# --- output formats (the partners reconcile these files automatically) ------


def fmt_input_date(value: datetime) -> str:
    """14/10/2026 00:44:05 (24 hours, no AM/PM)"""
    return f"{value:%d/%m/%Y %H:%M:%S}"


def fmt_day(value: datetime) -> str:
    """14/10/2026"""
    return f"{value:%d/%m/%Y}"


def fmt_default_datetime(value: datetime) -> str:
    """14/10/2026 00:44:05"""
    return f"{value:%d/%m/%Y %H:%M:%S}"


# Format of the date columns read from the database; the other date columns
# use ``fmt_default_datetime`` (dd/mm/yyyy HH:MM:SS)
COLUMN_DATE_FORMATS = {
    "BUSINESS_DATE": fmt_day,
    "TF_PARTITION_DATE": fmt_day,
}
# Columns that are dates in the database but may come back as text
DATE_COLUMNS = {
    "BUSINESS_DATE",
    "TRANSFER_DATE",
    "REFILL_DATE",
    "TF_ETL_AT",
    "TF_PARTITION_DATE",
}
TEXT_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)
WHOLE_NUMBER_TEXT = re.compile(r"^(-?\d+)\.0+$")


def _format_date(column: str, value: datetime) -> str:
    return COLUMN_DATE_FORMATS.get(column, fmt_default_datetime)(value)


def to_text(column: str, value: Any) -> str:
    """Text written in the output for a value read from the database.

    * dates are written ``dd/mm/yyyy HH:MM:SS`` (``dd/mm/yyyy`` for the day
      columns), never with AM/PM, milliseconds or a time zone;
    * whole numbers are written without decimals (``50000.00`` -> ``50000``),
      other numbers keep their decimals.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return _format_date(column, value)
    if isinstance(value, date):
        return _format_date(column, datetime.combine(value, datetime.min.time()))
    if isinstance(value, Decimal):
        return str(int(value)) if value == value.to_integral_value() else format(value, "f")
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    text = str(value).strip()
    if column in DATE_COLUMNS:
        for text_format in TEXT_DATE_FORMATS:
            try:
                return _format_date(column, datetime.strptime(text, text_format))
            except ValueError:
                continue
    whole = WHOLE_NUMBER_TEXT.match(text)
    return whole.group(1) if whole else text


# --- decision ---------------------------------------------------------------


def decide_reply(
    core: Optional[dict[str, Any]], bccs: Optional[dict[str, Any]]
) -> str:
    """Final status of a transaction, from the RESPONSE_CODE of BCCS only.

    * not found in the core table (B1), or not found in BCCS (B2)  -> TF
    * RESPONSE_CODE = 0                                            -> TS
    * RESPONSE_CODE = 7007 (timeout)                               -> TA
    * any other RESPONSE_CODE                                      -> TF

    The DESCRIPTION is not used to decide.
    """
    if core is None or bccs is None:
        return TF
    code = to_text("RESPONSE_CODE", bccs.get("RESPONSE_CODE"))
    if code in ("0", "0.0"):
        return TS
    if code == "7007":
        return TA
    return TF


def _latest(rows: list[dict[str, Any]], key: Any) -> dict[str, Any]:
    return max(rows, key=key)


def _id_key(row: dict[str, Any]) -> tuple[int, str]:
    raw = to_text("ID", row.get("ID"))
    return (int(raw), raw) if raw.isdigit() else (-1, raw)


def _date_key(row: dict[str, Any]) -> tuple[datetime, str]:
    value = row.get("TRANSFER_DATE")
    return (value if isinstance(value, datetime) else datetime.min, str(row.get("TRANSFER_ID")))


# --- values saved in the DWH ---------------------------------------------------


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _to_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if value is None or value == "":
        return None
    text = str(value).strip()
    for text_format in (*TEXT_DATE_FORMATS, *DATE_FORMATS):
        try:
            return datetime.strptime(text, text_format)
        except ValueError:
            continue
    return None


def coerce(col: Col, value: Any) -> Any:
    """The value as it is saved in the column of the detail table.

    A value that cannot be saved in its column (e.g. a text in a NUMBER column)
    is saved as NULL; text longer than the column is cut.
    """
    if value is None or value == "":
        return None
    if col.kind == "number":
        number = _to_decimal(value)
    elif col.kind == "datetime":
        number = _to_datetime(value)
    else:
        return to_text(col.output, value)[: col.size]
    if number is None:
        logger.warning("VPG: value %r does not fit the column %s", value, col.db)
    return number


def render(col: Col, value: Any) -> str:
    """Text written in the output file for a saved value (same rules whether the
    output is built after the processing or rebuilt from the saved rows)."""
    if value is None:
        return ""
    if col.kind == "text":
        return str(value)
    if col.kind == "number":
        return to_text(col.output, value)
    if col.output == "date":
        return fmt_input_date(value)
    return _format_date(col.output, value)


def record_to_row(record: dict[str, Any]) -> list[str]:
    return [render(col, record.get(col.db.lower())) for col in SPEC]


class VPGHandler(BusinessHandler):
    value = "VPG"
    label = "VPG"
    columns = (
        "transID",
        "date",
        "Phone_NO",
        "Type",
        "Amount",
        "Error_code",
        "Detail",
        "Provider",
    )
    output_columns = OUTPUT_COLUMNS
    output_groups = OUTPUT_GROUPS
    detail_table = DETAIL_TABLE

    def validate_data(self, rows: list[list[str]]) -> list[str]:
        errors: list[str] = []
        for number, row in enumerate(rows, start=2):  # row 1 is the header
            if len(errors) >= MAX_REPORTED_ERRORS:
                errors.append("...")
                break
            if not row[0].strip():
                errors.append(f"Row {number}: transID is empty")
            elif parse_date(row[1]) is None:
                errors.append(f"Row {number}: invalid date {row[1]!r}")
            elif row[4].strip() and _to_decimal(row[4]) is None:
                errors.append(f"Row {number}: invalid Amount {row[4]!r}")
        return errors

    def result_from_records(self, records: list[dict[str, Any]]) -> ProcessResult:
        return ProcessResult(
            columns=list(OUTPUT_COLUMNS),
            groups=list(OUTPUT_GROUPS),
            rows=[record_to_row(record) for record in records],
        )

    def process(self, validation: ValidationResult) -> ProcessResult:
        rows = validation.rows
        trans_ids = list(dict.fromkeys(r[0].strip() for r in rows))
        dates = [d for d in (parse_date(r[1]) for r in rows) if d is not None]
        first_day = datetime.combine(min(dates).date(), datetime.min.time())
        last_day = datetime.combine(max(dates).date(), datetime.min.time())

        try:
            core_rows = query_in_chunks(
                CONNECTION,
                CORE_SQL,
                trans_ids,
                {"date_from": first_day, "date_to": last_day + timedelta(days=1)},
            )
            core_by_id: dict[str, list[dict[str, Any]]] = {}
            for row in core_rows:
                core_by_id.setdefault(to_text("FIELD6", row["FIELD6"]), []).append(row)
            core_best = {k: _latest(v, _date_key) for k, v in core_by_id.items()}

            field8s = list(
                dict.fromkeys(
                    to_text("FIELD8", r["FIELD8"])
                    for r in core_best.values()
                    if to_text("FIELD8", r["FIELD8"])
                )
            )
            bccs_by_id: dict[str, list[dict[str, Any]]] = {}
            if field8s:
                bccs_rows = query_in_chunks(
                    CONNECTION,
                    BCCS_SQL,
                    field8s,
                    # BCCS is partitioned by day: one day before, two after
                    {
                        "date_from": first_day - timedelta(days=1),
                        "date_to": last_day + timedelta(days=2),
                    },
                )
                for row in bccs_rows:
                    bccs_by_id.setdefault(to_text("TRANS_ID", row["TRANS_ID"]), []).append(row)
            bccs_best = {k: _latest(v, _id_key) for k, v in bccs_by_id.items()}
        except LookupError as ex:
            raise ProcessError(str(ex)) from ex
        except Exception as ex:  # pylint: disable=broad-except
            logger.exception("VPG query failed")
            raise ProcessError("Query on the data source failed") from ex

        records: list[dict[str, Any]] = []
        summary = {TS: 0, TA: 0, TF: 0}
        for row in rows:
            trans_id = row[0].strip()
            core = core_best.get(trans_id)
            bccs = bccs_best.get(to_text("FIELD8", core["FIELD8"])) if core else None
            reply = decide_reply(core, bccs)
            summary[reply] += 1
            source: dict[str, Any] = {
                "transID": trans_id,
                "date": parse_date(row[1]),
                "Phone_NO": row[2],
                "Type": row[3],
                "Amount": row[4],
                "Error_code": row[5],
                "Detail": row[6],
                "Provider": row[7],
                "Reply": reply,
                **(core or {}),
                **(bccs or {}),
            }
            records.append(
                {col.db.lower(): coerce(col, source.get(col.output)) for col in SPEC}
            )

        return ProcessResult(
            columns=list(OUTPUT_COLUMNS),
            groups=list(OUTPUT_GROUPS),
            rows=[record_to_row(record) for record in records],
            summary=summary,
            records=records,
        )
