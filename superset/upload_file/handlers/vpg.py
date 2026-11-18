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
    NOT_FOUND_MESSAGE,
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


# Columns of the detail table of the DWH, in order. ``output`` is the key of the
# value in the source row (the name of the DWH column, or the db name for the
# columns that are computed); ``db`` is the column of
# UPLOAD_FILE_VPG_RESULT_DETAIL. Keep it in line with
# docs/upload_file_dwh_tables.sql.
DETAIL_SPEC: tuple[Col, ...] = (
    # what the user typed in the uploaded file, saved as it is (only the transID
    # and the date are required, the other cells may be empty)
    Col("INPUT_TRANS_ID", "INPUT_TRANS_ID", "text", "input", 64),
    Col("INPUT_DATE", "INPUT_DATE", "datetime", "input"),
    Col("INPUT_PHONE_NO", "INPUT_PHONE_NO", "text", "input", 32),
    Col("INPUT_TYPE", "INPUT_TYPE", "text", "input", 64),
    Col("INPUT_AMOUNT", "INPUT_AMOUNT", "number", "input"),
    Col("INPUT_ERROR_CODE", "INPUT_ERROR_CODE", "text", "input", 64),
    Col("INPUT_DETAIL", "INPUT_DETAIL", "text", "input", 1000),
    Col("INPUT_PROVIDER", "INPUT_PROVIDER", "text", "input", 64),
    # what the DWH says about the transaction (the typed value only when the DWH
    # has nothing)
    Col("RESULT_PHONE_NO", "RESULT_PHONE_NO", "text", "input", 32),
    Col("RESULT_TYPE", "RESULT_TYPE", "text", "input", 64),
    Col("RESULT_AMOUNT", "RESULT_AMOUNT", "number", "input"),
    Col("RESULT_ERROR_CODE", "RESULT_ERROR_CODE", "text", "input", 16),
    Col("RESULT_DETAIL", "RESULT_DETAIL", "text", "input", 1000),
    Col("RESULT_PROVIDER", "RESULT_PROVIDER", "text", "input", 64),
    # final answer: TS / TA / TF
    Col("RESULT_STATUS", "RESULT_STATUS", "text", "reply", 8),
    # from CUSTOMER_NAME (SFT_<partner>_VPG): the second part, e.g. BCEL
    Col("PARTNER_NAME", "PARTNER_NAME", "text", "input", 64),
    # RPT_B1_009_026_TRANS_HISTORY__FA (B1)
    Col("MERCHANT_TRANSID", "MERCHANT_TRANSID", "text", "core", 64),  # FIELD6
    Col("BUSINESS_DATE", "BUSINESS_DATE", "datetime", "core"),
    Col("TRANSFER_DATE", "TRANSFER_DATE", "datetime", "core"),
    Col("TRANSFER_ID", "TRANSFER_ID", "text", "core", 64),
    Col("SENDER_MSISDN", "SENDER_MSISDN", "text", "core", 32),
    Col("FIELD4", "FIELD4", "number", "core"),
    Col("UMONEY_TRANSACTION_ID", "UMONEY_TRANSACTION_ID", "text", "core", 64),  # FIELD8
    Col("TXN_STATUS", "TXN_STATUS", "text", "core", 16),
    # ods.bccs3_topup_wallet_charge_history__fa (B2)
    Col("ID", "ID", "text", "bccs", 64),
    Col("TRANS_ID", "TRANS_ID", "text", "bccs", 64),
    Col("REFILL_AMOUNT", "REFILL_AMOUNT", "number", "bccs"),
    Col("REFILL_DATE", "REFILL_DATE", "datetime", "bccs"),
    Col("REFILL_ISDN", "REFILL_ISDN", "text", "bccs", 32),
    Col("VAT", "VAT", "number", "bccs"),
    Col("DISCOUNT", "DISCOUNT", "number", "bccs"),
    Col("TELECOM_SERVICE_ID", "TELECOM_SERVICE_ID", "text", "bccs", 64),
    Col("PAY_TYPE", "PAY_TYPE", "text", "bccs", 64),
    Col("THIRD_PARTY_CODE", "THIRD_PARTY_CODE", "text", "bccs", 16),  # RESPONSE_CODE
    Col("THIRD_PARTY_DESCRIPTION", "THIRD_PARTY_DESCRIPTION", "text", "bccs", 1000),  # DESCRIPTION
    Col("CUSTOMER_NAME", "CUSTOMER_NAME", "text", "bccs", 256),
    Col("APP_NAME", "APP_NAME", "text", "bccs", 128),
    Col("PAYMENT_ID", "PAYMENT_ID", "text", "bccs", 64),
    Col("SALE_TRANS_ID", "SALE_TRANS_ID", "text", "bccs", 64),
    Col("ADJUST_DEBIT_TRANS_ID", "ADJUST_DEBIT_TRANS_ID", "text", "bccs", 64),
    Col("PREPAID_CODE", "PREPAID_CODE", "text", "bccs", 64),
    Col("PRODUCT_CODE", "PRODUCT_CODE", "text", "bccs", 64),
    Col("TRACE_ID", "TRACE_ID", "text", "bccs", 128),
    Col("TF_ETL_AT", "TF_ETL_AT", "datetime", "bccs"),
)
_SPEC_BY_KEY = {c.output: c for c in DETAIL_SPEC}

# The output (page and downloaded files, see Output.xlsx): (column name, column of
# the detail table, colour group)
OUTPUT_SPEC: tuple[tuple[str, str, str], ...] = (
    ("transID", "INPUT_TRANS_ID", "input"),
    ("date", "INPUT_DATE", "input"),
    ("Phone_NO", "RESULT_PHONE_NO", "input"),
    ("Type", "RESULT_TYPE", "input"),
    ("Amount", "RESULT_AMOUNT", "input"),
    ("Error_code", "RESULT_ERROR_CODE", "input"),
    ("Detail", "RESULT_DETAIL", "input"),
    ("Provider", "RESULT_PROVIDER", "input"),
    ("RESULT_STATUS", "RESULT_STATUS", "reply"),
    ("PARTNER_NAME", "PARTNER_NAME", "input"),
    ("TRANSFER_ID", "TRANSFER_ID", "core"),
    ("ORIGINAL_AMOUNT", "FIELD4", "core"),
    ("UMONEY_TRANSACTION_ID", "UMONEY_TRANSACTION_ID", "core"),
    ("TXN_STATUS", "TXN_STATUS", "core"),
    ("THIRD_PARTY_CODE", "THIRD_PARTY_CODE", "bccs"),
    ("THIRD_PARTY_DESCRIPTION", "THIRD_PARTY_DESCRIPTION", "bccs"),
)
OUTPUT_COLUMNS = [name for name, _, _ in OUTPUT_SPEC]
# Output columns that hold an amount (formatted as money in the Excel file)
OUTPUT_NUMBER_COLUMNS = ("Amount", "ORIGINAL_AMOUNT")
OUTPUT_GROUPS = [group for _, _, group in OUTPUT_SPEC]

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
    *[Column(c.db.lower(), _DETAIL_TYPES[c.kind](c)) for c in DETAIL_SPEC],
    schema=DWH_SCHEMA,
)

# FIELD6 and FIELD8 are named MERCHANT_TRANSID and UMONEY_TRANSACTION_ID
CORE_SQL = """
    SELECT FIELD1, FIELD2, FIELD3, FIELD6 AS MERCHANT_TRANSID, BUSINESS_DATE, TRANSFER_DATE,
           TRANSFER_ID, SENDER_MSISDN, FIELD4, FIELD8 AS UMONEY_TRANSACTION_ID,
           TXN_STATUS
    FROM RPT_B1_009_026_TRANS_HISTORY__FA
    WHERE BUSINESS_DATE >= :date_from
      AND BUSINESS_DATE < :date_to
      AND FIELD2 LIKE 'SFT\\_%\\_VPG' ESCAPE '\\'
      AND FIELD6 IN :ids
"""
BCCS_SQL = """
    SELECT ID, TRANS_ID, REFILL_AMOUNT, REFILL_DATE, REFILL_ISDN, VAT, DISCOUNT,
           TELECOM_SERVICE_ID, PAY_TYPE, RESPONSE_CODE AS THIRD_PARTY_CODE,
           DESCRIPTION AS THIRD_PARTY_DESCRIPTION, CUSTOMER_NAME, APP_NAME,
           PAYMENT_ID, SALE_TRANS_ID, ADJUST_DEBIT_TRANS_ID, PREPAID_CODE,
           PRODUCT_CODE, TRACE_ID, TF_ETL_AT
    FROM ods.bccs3_topup_wallet_charge_history__fa
    WHERE TF_PARTITION_DATE >= :date_from
      AND TF_PARTITION_DATE < :date_to
      AND trans_id IN :ids
"""

# The "date" column of the uploaded file must be dd/mm/yyyy HH:MM:SS (two digits
# each, 24 hours), the seconds being optional (missing = 0): it chooses the days
# that are searched in the DWH, so a date that is silently read the wrong way
# (day/month swapped) would make every transaction "not found".
# Also accepted: the ISO form yyyy-mm-dd HH:MM[:SS] (no day/month doubt), and an
# hour with one digit (0:00:01) as Excel shows it
INPUT_DATE_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)
INPUT_DATE_PATTERN = re.compile(
    r"^(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}) \d{1,2}:\d{2}(:\d{2})?$"
)

# Formats used to read dates that come back from the DWH as text
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


def parse_input_date(value: str) -> Optional[datetime]:
    """The date of an uploaded row, or None if it is not dd/mm/yyyy HH:MM[:SS]
    (or yyyy-mm-dd HH:MM[:SS])."""
    value = value.strip()
    if not INPUT_DATE_PATTERN.match(value):
        return None
    for date_format in INPUT_DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None  # e.g. 32/13/2026 or 25:61:00


NORMAL_DATE_FORMAT = "%d/%m/%Y %H:%M:%S"

# Characters that look like nothing but break the match of a transID (BOM, zero
# width characters, non breaking space)
INVISIBLE_CHARS = dict.fromkeys(map(ord, "\ufeff\u200b\u200c\u200d\u2060\u00a0"), None)
SCIENTIFIC_NUMBER = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")


def clean_trans_id(value: str) -> str:
    """The transID as it is looked up: no invisible character, no space around,
    and no ``.0`` that a spreadsheet adds to a number (1057018085.0)."""
    text = value.translate(INVISIBLE_CHARS).strip()
    whole = WHOLE_NUMBER_TEXT.match(text)
    return whole.group(1) if whole else text


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
    code = to_text("THIRD_PARTY_CODE", bccs.get("THIRD_PARTY_CODE"))
    if code in ("0", "0.0"):
        return TS
    if code == "7007":
        return TA
    return TF


# Provider of the output when the file does not give one
DEFAULT_PROVIDER = "UNITEL"

# VPG error code and detail of the output, from the final answer:
# success 00, timeout 92, failed 90
RESULT_TEXT = {
    TS: ("00", "Transaction success"),
    TA: ("92", "Transaction timeout. Please check more with Unitel"),
    TF: ("90", "Transaction failed"),
}
# Error code of an INPUT_ERROR_CODE found in the core table (B1), from its
# TXN_STATUS: TS 00, TF 90, any other 92 (the same codes as RESULT_TEXT)
CORE_ERROR_CODES = {TS: "00", TF: "90"}
CORE_OTHER_ERROR_CODE = "92"


def input_from_core(core: Optional[dict[str, Any]], reply: str) -> dict[str, Any]:
    """Values of the INPUT_* columns found in the core table (B1) from the transID.

    They complete what the user left empty in the uploaded file:

    * phone     = FIELD1
    * type      = the last part of FIELD3 (after the last ``_``)
    * amount    = FIELD4
    * error code from TXN_STATUS (TS 00, TF 90, other 92)
    * detail from the final answer (see ``decide_reply``)
    * provider  = UNITEL

    A transaction that is not in B1 is a failed one: nothing to read, the error
    code and the detail say it failed.
    """
    detail = RESULT_TEXT[reply][1]
    if core is None:
        return {
            "INPUT_ERROR_CODE": CORE_ERROR_CODES[TF],
            "INPUT_DETAIL": detail,
            "INPUT_PROVIDER": DEFAULT_PROVIDER,
        }
    last_part = re.search(r"[^_]+$", to_text("FIELD3", core.get("FIELD3")))
    status = to_text("TXN_STATUS", core.get("TXN_STATUS")).upper()
    return {
        "INPUT_PHONE_NO": to_text("FIELD1", core.get("FIELD1")) or None,
        "INPUT_TYPE": last_part.group(0) if last_part else None,
        "INPUT_AMOUNT": core.get("FIELD4"),
        "INPUT_ERROR_CODE": CORE_ERROR_CODES.get(status, CORE_OTHER_ERROR_CODE),
        "INPUT_DETAIL": detail,
        "INPUT_PROVIDER": DEFAULT_PROVIDER,
    }


def partner_name(code: Any) -> str:
    """BCEL from the partner code SFT_BCEL_VPG: what is between the first and
    the last underscore."""
    parts = str(code or "").strip().split("_")
    if len(parts) >= 3:
        return "_".join(parts[1:-1]).strip()
    return parts[1].strip() if len(parts) == 2 else ""


def _first(*values: Any) -> Any:
    """First value that is not empty."""
    return next((v for v in values if v is not None and str(v).strip() != ""), None)


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
        if number is not None:
            number = number.replace(microsecond=0)  # to the second
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
    if col.output == "INPUT_DATE":
        return fmt_input_date(value)
    return _format_date(col.output, value)


def record_to_row(record: dict[str, Any]) -> list[str]:
    row = [render(_SPEC_BY_KEY[db], record.get(db.lower())) for _, db, _ in OUTPUT_SPEC]
    # No BCCS row: the transaction was not found in the DWH, say it where the
    # third party description would be
    if record.get("trans_id") is None:
        for index, (_, db, _) in enumerate(OUTPUT_SPEC):
            if db == "THIRD_PARTY_DESCRIPTION" and not row[index]:
                row[index] = NOT_FOUND_MESSAGE
    return row


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
    template_descriptions = {
        "transID": "Transaction ID. The system uses it to check the other information in "
        "Umoney's systems, so it must match the transaction to be checked",
        "date": "Transaction date and time, format dd/mm/yyyy HH:MM:SS. It is used to look "
        "up the transaction at the right time",
        "Phone_NO": "Phone number of the customer who made the transaction",
        "Type": "Transaction type",
        "Amount": "Amount, value of the transaction",
        "Error_code": "Error code: 00 successful transaction, 90 failed transaction, "
        "92 transaction timeout",
        "Detail": "Error detail",
        "Provider": "Provider, UNITEL by default",
    }
    template_descriptions_vi = {
        "transID": "Mã giao dịch, hệ thống sẽ dựa theo thông tin này để kiểm tra các thông "
        "tin còn lại trong hệ thống của Umoney vì vậy cột này cần đảm bảo đúng với giao "
        "dịch cần kiểm tra",
        "date": "Ngày giờ giao dịch, dạng dd/mm/yyyy HH:MM:SS đây là thời gian để đảm bảo "
        "kiểm tra đúng thời gian phát sinh giao dịch",
        "Phone_NO": "Số điện thoại của khách hàng thực hiện giao dịch",
        "Type": "Loại giao dịch",
        "Amount": "Số tiền, giá trị giao dịch",
        "Error_code": "Mã lỗi: 00 giao dịch thành công, 90 giao dịch thất bại, "
        "92 giao dịch timeout",
        "Detail": "Chi tiết lỗi",
        "Provider": "Đơn vị cung cấp, mặc định là UNITEL",
    }
    template_required_columns = frozenset({"transID", "date"})
    template_sample_rows = [
        [
            "1057018085",
            "14/10/2026 00:44:05",
            "2099090028",
            "PREPAID",
            "50000",
            "90",
            "Request not response from provider",
            "UNITEL",
        ],
        [
            "1057019308",
            "14/10/2026 00:54:55",
            "2098080320",
            "PREPAID",
            "5000",
            "90",
            "Request not response from provider",
            "UNITEL",
        ],
    ]
    template_number_columns = frozenset({"Amount"})

    def normalize_rows(self, rows: list[list[str]]) -> list[str]:
        """Write every valid date as dd/mm/yyyy HH:MM:SS (a missing second is 00),
        so the preview, the result and the saved rows all show the same thing.
        The invalid ones are left as they are: ``validate_data`` reports them."""
        for row in rows:
            row[0] = clean_trans_id(row[0])
            row[1] = row[1].translate(INVISIBLE_CHARS).strip()
            parsed = parse_input_date(row[1])
            if parsed is not None:
                row[1] = parsed.strftime(NORMAL_DATE_FORMAT)
        return []

    def validate_data(self, rows: list[list[str]]) -> list[str]:
        errors: list[str] = []
        bad_date = False
        for number, row in enumerate(rows, start=2):  # row 1 is the header
            if len(errors) >= MAX_REPORTED_ERRORS:
                errors.append("...")
                break
            if not row[0].strip():
                errors.append(f"Row {number}: transID is empty")
            elif SCIENTIFIC_NUMBER.match(row[0]):
                errors.append(
                    f"Row {number}: transID {row[0]!r} is in scientific notation, "
                    "format the column as Text so the full number is kept"
                )
            elif parse_input_date(row[1]) is None:
                bad_date = True
                errors.append(
                    f"Row {number}: date {row[1]!r} is not in the format "
                    "dd/mm/yyyy HH:MM:SS (seconds are optional)"
                )
        if bad_date:
            errors.append(
                "Tip: in Excel, format the date column as Text and type "
                "dd/mm/yyyy HH:MM:SS (an Excel date value shown as m/d/yy can "
                "swap the day and the month)"
            )
        return errors

    def result_from_records(self, records: list[dict[str, Any]]) -> ProcessResult:
        return ProcessResult(
            columns=list(OUTPUT_COLUMNS),
            groups=list(OUTPUT_GROUPS),
            rows=[record_to_row(record) for record in records],
            number_columns=OUTPUT_NUMBER_COLUMNS,
        )

    def process(self, validation: ValidationResult) -> ProcessResult:
        rows = validation.rows
        trans_ids = list(dict.fromkeys(r[0].strip() for r in rows))
        dates = [d for d in (parse_input_date(r[1]) for r in rows) if d is not None]
        first_day = datetime.combine(min(dates).date(), datetime.min.time())
        last_day = datetime.combine(max(dates).date(), datetime.min.time())

        try:
            core_rows = query_in_chunks(
                CONNECTION,
                CORE_SQL,
                trans_ids,
                # The BUSINESS_DATE of a transaction made just before midnight can
                # be the next day (or the day before for the first ones): one
                # more day on each side of the days of the file
                {
                    "date_from": first_day - timedelta(days=1),
                    "date_to": last_day + timedelta(days=2),
                },
            )
            core_by_id: dict[str, list[dict[str, Any]]] = {}
            for row in core_rows:
                core_by_id.setdefault(to_text("MERCHANT_TRANSID", row["MERCHANT_TRANSID"]), []).append(row)
            core_best = {k: _latest(v, _date_key) for k, v in core_by_id.items()}

            field8s = list(
                dict.fromkeys(
                    to_text("UMONEY_TRANSACTION_ID", r["UMONEY_TRANSACTION_ID"])
                    for r in core_best.values()
                    if to_text("UMONEY_TRANSACTION_ID", r["UMONEY_TRANSACTION_ID"])
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
            bccs = bccs_best.get(to_text("UMONEY_TRANSACTION_ID", core["UMONEY_TRANSACTION_ID"])) if core else None
            reply = decide_reply(core, bccs)
            summary[reply] += 1
            input_values = {
                "INPUT_TRANS_ID": trans_id,
                "INPUT_DATE": parse_input_date(row[1]),
                "INPUT_PHONE_NO": row[2],
                "INPUT_TYPE": row[3],
                "INPUT_AMOUNT": row[4],
                "INPUT_ERROR_CODE": row[5],
                "INPUT_DETAIL": row[6],
                "INPUT_PROVIDER": row[7],
            }
            core_values = core or {}
            bccs_values = bccs or {}
            # What B1 says about the transaction (see ``input_from_core``): it fills
            # the INPUT_* cells the user left empty and is the phone, type and
            # amount of the output. The typed value is only used when B1 has
            # nothing (a transaction that is not in B1). Error_code and Detail of
            # the output are the VPG code of the final answer (RESULT_TEXT). The
            # BCCS columns (PAY_TYPE...) are saved as they are but do not feed
            # these columns.
            found = input_from_core(core, reply)
            source: dict[str, Any] = {
                **core_values,
                **bccs_values,
                **input_values,
                "RESULT_PHONE_NO": _first(
                    found.get("INPUT_PHONE_NO"), input_values["INPUT_PHONE_NO"]
                ),
                "RESULT_TYPE": _first(
                    found.get("INPUT_TYPE"), input_values["INPUT_TYPE"]
                ),
                "RESULT_AMOUNT": _first(
                    found.get("INPUT_AMOUNT"), input_values["INPUT_AMOUNT"]
                ),
                "RESULT_ERROR_CODE": RESULT_TEXT[reply][0],
                "RESULT_DETAIL": RESULT_TEXT[reply][1],
                "RESULT_PROVIDER": _first(
                    input_values["INPUT_PROVIDER"], found["INPUT_PROVIDER"]
                ),
                "RESULT_STATUS": reply,
                "PARTNER_NAME": partner_name(
                    _first(bccs_values.get("CUSTOMER_NAME"), core_values.get("FIELD2"))
                ),
            }
            # An INPUT_* cell the user left empty (or filled with something that
            # cannot be saved, e.g. a text as Amount) is completed from B1
            for input_key, value in found.items():
                if coerce(_SPEC_BY_KEY[input_key], source.get(input_key)) is None:
                    source[input_key] = value
            record = {
                col.db.lower(): coerce(col, source.get(col.output))
                for col in DETAIL_SPEC
            }
            records.append(record)

        return ProcessResult(
            columns=list(OUTPUT_COLUMNS),
            groups=list(OUTPUT_GROUPS),
            rows=[record_to_row(record) for record in records],
            number_columns=OUTPUT_NUMBER_COLUMNS,
            summary=summary,
            records=records,
        )
