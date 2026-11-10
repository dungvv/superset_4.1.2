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
"""Read an uploaded CSV / Excel file and validate it against a business type.

Generic helpers shared by every business type handler. The rules that belong
to one business type live in ``superset/upload_file/handlers/``.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

ALLOWED_EXTENSIONS = {"csv", "xlsx"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
PREVIEW_ROWS = 50
MAX_ROWS = 100_000
# Stop reading a sheet after this many consecutive blank rows
MAX_BLANK_STREAK = 1000


class UploadFileError(Exception):
    """The file cannot be read at all (unsupported type, corrupted, ...)."""


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    total_rows: int = 0
    preview: list[list[str]] = field(default_factory=list)
    # Every data row, in template column order (not sent to the browser)
    rows: list[list[str]] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "columns": self.columns,
            "total_rows": self.total_rows,
            "preview": self.preview,
        }


def _norm(value: str) -> str:
    return value.replace("﻿", "").strip().lower()


def _cell_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


_DMY_TIME_FORMATS = {"dd/mm/yyyy hh:mm:ss", "dd/mm/yyyy hh:mm"}


def _is_dmy_hms_format(number_format: Any) -> bool:
    """True for an Excel number format that shows ``dd/mm/yyyy hh:mm[:ss]``.

    An Excel date is a number: with a day/month ambiguous format (e.g. ``m/d/yy``)
    ``06/11/2026`` typed by a user can silently become the 11th of June. So a
    date cell is only trusted when the column is displayed as day/month/year.
    """
    if not isinstance(number_format, str):
        return False
    text = re.sub(r"\[[^\]]*\]", "", number_format.split(";")[0])  # [$-409], [Red]...
    text = re.sub(r'[\\"]', "", text)
    return re.sub(r"\s+", " ", text).strip().lower() in _DMY_TIME_FORMATS


def _xlsx_cell_to_str(cell: Any) -> str:
    value = cell.value
    if isinstance(value, datetime) and _is_dmy_hms_format(cell.number_format):
        return value.strftime("%d/%m/%Y %H:%M:%S")
    return _cell_to_str(value)


def _trim(row: list[str]) -> list[str]:
    """Drop the trailing empty cells of a row."""
    while row and row[-1] == "":
        row.pop()
    return row


def _read_csv(content: bytes) -> list[list[str]]:
    for encoding in ("utf-8-sig", "cp1258", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 never fails
        raise UploadFileError("Unable to decode file")

    first_line = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=first_line.count)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [_trim([cell.strip() for cell in row]) for row in reader]


def _read_xlsx(content: bytes) -> list[list[str]]:
    from openpyxl import load_workbook  # pylint: disable=import-outside-toplevel

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as ex:  # pylint: disable=broad-except
        raise UploadFileError("Unable to read Excel file") from ex
    try:
        sheet = workbook.worksheets[0]
        # The declared dimension of exported files is often wrong (e.g. the
        # whole column is formatted), so never trust it
        sheet.reset_dimensions()
        rows: list[list[str]] = []
        blank_streak = 0
        for raw in sheet.iter_rows():
            row = _trim([_xlsx_cell_to_str(cell) for cell in raw])
            if row:
                rows.append(row)
                blank_streak = 0
                if len(rows) > MAX_ROWS:
                    raise UploadFileError(f"File has more than {MAX_ROWS} rows")
            else:
                blank_streak += 1
                if blank_streak >= MAX_BLANK_STREAK:
                    break
        return rows
    finally:
        workbook.close()


def read_rows(filename: str, content: bytes) -> list[list[str]]:
    """Return every non-empty row of the file, header first."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadFileError(
            ".xls is not supported, please save the file as .xlsx or .csv"
            if extension == "xls"
            else "Only CSV or Excel (.xlsx) files are supported"
        )
    if len(content) > MAX_FILE_SIZE:
        raise UploadFileError("File size must not exceed 5 MB")
    rows = _read_csv(content) if extension == "csv" else _read_xlsx(content)
    rows = [row for row in rows if row]
    if len(rows) > MAX_ROWS + 1:
        raise UploadFileError(f"File has more than {MAX_ROWS} rows")
    return rows


def validate_template(
    label: str, expected: tuple[str, ...], rows: list[list[str]]
) -> ValidationResult:
    """Check the header of ``rows`` against the template columns ``expected``."""
    if not rows:
        return ValidationResult(valid=False, errors=["File is empty"])

    header, body = rows[0], rows[1:]
    positions = [_norm(h) for h in header]
    expected_norm = [_norm(c) for c in expected]

    missing = [c for c, n in zip(expected, expected_norm) if n not in positions]
    extra = [
        (h.strip() or "(empty)")
        for h, n in zip(header, positions)
        if n not in expected_norm
    ]
    duplicated = [c for c, n in zip(expected, expected_norm) if positions.count(n) > 1]

    errors: list[str] = []
    if len(header) != len(expected) or missing or extra or duplicated:
        errors.append(
            f"File must have exactly {len(expected)} columns as in the "
            f"{label} template"
        )
    if missing:
        errors.append(f"Missing: {', '.join(missing)}")
    if extra:
        errors.append(f"Unexpected: {', '.join(extra)}")
    if duplicated:
        errors.append(f"Duplicated: {', '.join(duplicated)}")
    if not errors and not body:
        errors.append("File has no data rows")
    if errors:
        return ValidationResult(valid=False, errors=errors, columns=header)

    # Re-order the columns to follow the template
    indexes = [positions.index(n) for n in expected_norm]
    ordered = [[row[i] if i < len(row) else "" for i in indexes] for row in body]
    return ValidationResult(
        valid=True,
        columns=list(expected),
        total_rows=len(ordered),
        preview=ordered[:PREVIEW_ROWS],
        rows=ordered,
    )
