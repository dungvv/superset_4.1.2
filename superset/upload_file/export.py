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
"""Build the downloadable files (CSV / Excel) of a processed upload."""

import csv
import io
from typing import Any

from superset.upload_file.handlers.base import BusinessHandler, ProcessResult

# The CSV follows the sample given by the partners: tab separated, UTF-8
# without BOM, "\n" line endings.
CSV_DELIMITER = "\t"
CSV_LINE_TERMINATOR = "\n"

# Header / body colours by source of the column
GROUP_COLORS = {
    "input": {"header": "#44546A", "body": None},  # from the uploaded file
    "reply": {"header": "#2E7D32", "body": None},  # final answer
    "core": {"header": "#ED7D31", "body": "#FCE4D6"},  # table 009 (orange)
    "bccs": {"header": "#7F5539", "body": "#EADBC8"},  # BCCS table (brown)
}
REPLY_COLORS = {
    "TS": {"bg_color": "#C6EFCE", "font_color": "#006100"},
    "TA": {"bg_color": "#FFEB9C", "font_color": "#9C5700"},
    "TF": {"bg_color": "#FFC7CE", "font_color": "#9C0006"},
}
MAX_COLUMN_WIDTH = 40
# Blank rows between the last data row and the statistics block
STATS_GAP = 3


def _stats(result: ProcessResult) -> list[tuple[str, int]]:
    """Statistics written at the end of the output files."""
    summary = result.summary
    return [
        ("TOTAL TXN", len(result.rows)),
        ("TOTAL TS", summary.get("TS", 0)),
        ("TOTAL TF", summary.get("TF", 0)),
        ("TOTAL TA", summary.get("TA", 0)),
    ]


def build_csv(result: ProcessResult, excel_hint: bool = False) -> bytes:
    """Tab separated CSV.

    ``excel_hint`` adds the ``sep=`` first line that makes Excel (Windows / Mac)
    split the columns whatever the list separator of the machine is. Other
    readers (Linux, partner systems) must not get it: it would be a data row.
    """
    buffer = io.StringIO(newline="")
    if excel_hint:
        buffer.write(f"sep={CSV_DELIMITER}{CSV_LINE_TERMINATOR}")
    writer = csv.writer(
        buffer, delimiter=CSV_DELIMITER, lineterminator=CSV_LINE_TERMINATOR
    )
    writer.writerow(result.columns)
    writer.writerows(result.rows)
    for _ in range(STATS_GAP):
        writer.writerow([])
    for label, count in _stats(result):
        writer.writerow([label, count])
    return buffer.getvalue().encode("utf-8")


def build_xlsx(result: ProcessResult) -> bytes:
    import xlsxwriter  # pylint: disable=import-outside-toplevel

    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    sheet = workbook.add_worksheet("Result")

    base: dict[str, Any] = {"border": 1, "border_color": "#D9D9D9", "valign": "vcenter"}
    header_formats = {
        group: workbook.add_format(
            {
                **base,
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": colors["header"],
                "align": "center",
                "text_wrap": True,
            }
        )
        for group, colors in GROUP_COLORS.items()
    }
    body_formats = {
        group: workbook.add_format(
            {**base, **({"bg_color": colors["body"]} if colors["body"] else {})}
        )
        for group, colors in GROUP_COLORS.items()
    }
    reply_formats = {
        value: workbook.add_format({**base, **style, "bold": True, "align": "center"})
        for value, style in REPLY_COLORS.items()
    }

    widths = [len(c) for c in result.columns]
    for col, name in enumerate(result.columns):
        sheet.write_string(0, col, name, header_formats[result.groups[col]])
    for row_index, row in enumerate(result.rows, start=1):
        for col, value in enumerate(row):
            group = result.groups[col]
            cell_format = (
                reply_formats.get(value, body_formats[group])
                if group == "reply"
                else body_formats[group]
            )
            # Always text: keeps long ids / leading zeros exactly as they are
            sheet.write_string(row_index, col, value, cell_format)
            widths[col] = max(widths[col], len(value))
    for col, width in enumerate(widths):
        sheet.set_column(col, col, min(width + 2, MAX_COLUMN_WIDTH))
    stats_label = workbook.add_format({"bold": True})
    stats_row = len(result.rows) + 1 + STATS_GAP
    for offset, (label, count) in enumerate(_stats(result)):
        sheet.write_string(stats_row + offset, 0, label, stats_label)
        sheet.write_number(stats_row + offset, 1, count)
    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, len(result.rows), len(result.columns) - 1)
    workbook.close()
    return buffer.getvalue()


def build_template_xlsx(handler: BusinessHandler) -> bytes:
    """Excel template of a business type.

    * ``Template``: the sheet to fill and upload (the file reader only reads the
      first sheet). It holds the header row only; the columns are formatted as
      Text (numbers for the number columns) so Excel does not turn
      ``06/11/2026`` into a date and does not drop the leading zeros.
    * ``Guide``: description of every column, the date rule and sample rows.
    """
    import xlsxwriter  # pylint: disable=import-outside-toplevel

    names = list(handler.columns)
    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    base: dict[str, Any] = {"font_name": "Arial", "font_size": 10, "valign": "top"}
    header = workbook.add_format(
        {**base, "bold": True, "font_color": "#FFFFFF", "bg_color": "#44546A",
         "align": "center", "valign": "vcenter", "border": 1}
    )
    text = workbook.add_format({**base, "num_format": "@"})
    number = workbook.add_format({**base, "num_format": "General"})
    cell = workbook.add_format({**base, "text_wrap": True, "border": 1, "border_color": "#D9D9D9"})
    bold = workbook.add_format({**base, "bold": True})
    title = workbook.add_format({**base, "bold": True, "font_size": 14})
    plain = workbook.add_format(base)
    wrapped = workbook.add_format({**base, "text_wrap": True})

    sheet = workbook.add_worksheet("Template")
    for col, name in enumerate(names):
        is_number = name in handler.template_number_columns
        sheet.set_column(col, col, max(len(name) + 6, 16), number if is_number else text)
        sheet.write_string(0, col, name, header)
    sheet.set_row(0, 22)
    sheet.freeze_panes(1, 0)

    guide = workbook.add_worksheet("Hướng dẫn")
    guide.set_column(0, 0, 18)
    guide.set_column(1, 1, 62)
    guide.set_column(2, 8, 24)
    guide.write_string(0, 0, f"Template {handler.label}", title)
    notes = [
        "Điền dữ liệu vào sheet 'Template' (dòng 1 là tên cột, dữ liệu từ dòng 2) rồi upload file này.",
        "Các cột có thể sắp xếp theo thứ tự bất kỳ, tên cột không phân biệt hoa thường nhưng phải đủ và đúng tên.",
        "Cột date phải đúng dạng dd/mm/yyyy HH:MM:SS hoặc dd/mm/yyyy HH:MM (ngày đứng trước, mỗi phần đủ 2 chữ số).",
        "File upload chỉ được đọc sheet đầu tiên.",
    ]
    for i, note in enumerate(notes, start=2):
        guide.write_string(i, 0, f"{i - 1}.", plain)
        guide.merge_range(i, 1, i, 8, note, wrapped)
        guide.set_row(i, 30 if len(note) > 110 else 16)
    row = len(notes) + 3
    for col, label in enumerate(("Cột", "Mô tả")):
        guide.write_string(row, col, label, header)
    for i, name in enumerate(names, start=row + 1):
        guide.write_string(i, 0, name, bold)
        guide.write_string(i, 1, handler.template_descriptions.get(name, ""), cell)
    row = row + len(names) + 3
    guide.write_string(row, 0, "Dữ liệu mẫu", bold)
    for col, name in enumerate(names):
        guide.write_string(row + 1, col, name, header)
    for i, sample in enumerate(handler.template_sample_rows, start=row + 2):
        for col, value in enumerate(sample):
            guide.write_string(i, col, value, cell)
    workbook.close()
    return buffer.getvalue()
