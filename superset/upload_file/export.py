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
import math
from typing import Any, Optional

from superset.upload_file.handlers.base import (
    BusinessHandler,
    NOT_FOUND_MESSAGE,
    ProcessResult,
)

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
# Header: bold capital letters are wider than the digits the column width is
# counted in, and the filter button takes room on the right
HEADER_LETTER_WIDTH = 1.3
HEADER_PADDING = 6
NOT_FOUND_FONT_COLOR = "#C00000"
# Borders of the tables of the template guide (visible, like the header)
TEMPLATE_BORDER_COLOR = "#000000"


def _to_number(value: str) -> Optional[float]:
    """The amount written in a cell, or None when it is empty / not a number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_csv(result: ProcessResult, excel_hint: bool = False) -> bytes:
    """Tab separated CSV.

    ``excel_hint`` adds the ``sep=`` first line that makes Excel (Windows / Mac)
    split the columns whatever the list separator of the machine is. Other
    readers (Linux, partner systems) must not get it: it would be a data row.
    """
    result = result.for_file()
    buffer = io.StringIO(newline="")
    if excel_hint:
        buffer.write(f"sep={CSV_DELIMITER}{CSV_LINE_TERMINATOR}")
    writer = csv.writer(
        buffer, delimiter=CSV_DELIMITER, lineterminator=CSV_LINE_TERMINATOR
    )
    writer.writerow(result.columns)
    writer.writerows(result.rows)
    return buffer.getvalue().encode("utf-8")


def build_xlsx(result: ProcessResult) -> bytes:
    import xlsxwriter  # pylint: disable=import-outside-toplevel

    result = result.for_file()
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
    # Amounts: thousand separator, no decimals, right aligned
    number_formats = {
        group: workbook.add_format(
            {
                **base,
                **({"bg_color": colors["body"]} if colors["body"] else {}),
                "num_format": "#,##0",
                "align": "right",
            }
        )
        for group, colors in GROUP_COLORS.items()
    }
    not_found_formats = {
        group: workbook.add_format(
            {
                **base,
                **({"bg_color": colors["body"]} if colors["body"] else {}),
                "font_color": NOT_FOUND_FONT_COLOR,
            }
        )
        for group, colors in GROUP_COLORS.items()
    }
    reply_formats = {
        value: workbook.add_format({**base, **style, "bold": True, "align": "center"})
        for value, style in REPLY_COLORS.items()
    }

    # The header must fit on one line, with the filter button
    header_widths = [
        math.ceil(len(c) * HEADER_LETTER_WIDTH) + HEADER_PADDING for c in result.columns
    ]
    widths = [0] * len(result.columns)
    for col, name in enumerate(result.columns):
        sheet.write_string(0, col, name, header_formats[result.groups[col]])
    for row_index, row in enumerate(result.rows, start=1):
        for col, value in enumerate(row):
            group = result.groups[col]
            if value == NOT_FOUND_MESSAGE:
                cell_format = not_found_formats[group]
            elif group == "reply":
                cell_format = reply_formats.get(value, body_formats[group])
            else:
                cell_format = body_formats[group]
            number = (
                _to_number(value) if result.columns[col] in result.number_columns else None
            )
            if number is not None:
                sheet.write_number(row_index, col, number, number_formats[group])
                widths[col] = max(widths[col], len(f"{number:,.0f}"))
                continue
            # Always text: keeps long ids / leading zeros exactly as they are
            sheet.write_string(row_index, col, value, cell_format)
            widths[col] = max(widths[col], len(value))
    for col, width in enumerate(widths):
        sheet.set_column(
            col, col, max(header_widths[col], min(width + 2, MAX_COLUMN_WIDTH))
        )
    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, len(result.rows), len(result.columns) - 1)
    workbook.close()
    return buffer.getvalue()


TEMPLATE_TEXT = {
    "en": {
        "sheet": "Guideline",
        "template": "Template {label}",
        "notes": [
            "Fill in the data in the 'Template' sheet (row 1 is the column names, data starts from row 2; delete the sample rows first), then upload this file.",
            "Only transID and date are required. The other columns are optional (they can be empty, or left out); columns that are not in the template are ignored. Column names are case-insensitive and can be in any order.",
            "The date column must be in the format dd/mm/yyyy HH:MM:SS or dd/mm/yyyy HH:MM (day first, day and month with 2 digits); yyyy-mm-dd HH:MM:SS is also accepted.",
            "Only the first sheet of the uploaded file is read.",
            "Columns marked with * are required.",
        ],
        "headers": ("Column", "Required", "Description"),
        "yes": "Yes",
        "no": "No",
        "sample": "Sample data",
    },
    "vi": {
        "sheet": "Hướng dẫn",
        "template": "Template {label}",
        "notes": [
            "Điền dữ liệu vào sheet 'Template' (dòng 1 là tên cột, dữ liệu từ dòng 2; hãy xóa các dòng mẫu trước) rồi upload file này.",
            "Chỉ bắt buộc 2 cột transID và date. Các cột còn lại không bắt buộc (có thể để trống hoặc bỏ hẳn), cột không có trong template sẽ bị bỏ qua. Tên cột không phân biệt hoa thường, thứ tự bất kỳ.",
            "Cột date phải đúng dạng dd/mm/yyyy HH:MM:SS hoặc dd/mm/yyyy HH:MM (ngày đứng trước, ngày và tháng đủ 2 chữ số); chấp nhận cả yyyy-mm-dd HH:MM:SS.",
            "File upload chỉ được đọc sheet đầu tiên.",
            "Các cột có dấu * là bắt buộc điền.",
        ],
        "headers": ("Cột", "Bắt buộc", "Mô tả"),
        "yes": "Có",
        "no": "Không",
        "sample": "Dữ liệu mẫu",
    },
}


def build_template_xlsx(handler: BusinessHandler) -> bytes:
    """Excel template of a business type, with 3 sheets.

    * ``Template``: the sheet to fill and upload (the file reader only reads the
      first sheet). It holds the header row and the sample rows; the columns are
      formatted as Text (numbers for the number columns) so Excel does not turn
      ``06/11/2026`` into a date and does not drop the leading zeros. The name
      of a required column ends with a red ``*``.
    * ``Hướng dẫn`` and ``Guideline``: the same guide in Vietnamese and in
      English: rules, required / optional and description of every column,
      sample rows.
    """
    import xlsxwriter  # pylint: disable=import-outside-toplevel

    names = list(handler.columns)
    required = handler.template_required_columns
    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
    base: dict[str, Any] = {"font_name": "Arial", "font_size": 10, "valign": "top"}
    head = {
        **base,
        "bold": True,
        "bg_color": "#D9D9D9",
        "align": "center",
        "valign": "vcenter",
        "border": 1,
        "border_color": TEMPLATE_BORDER_COLOR,
    }
    header = workbook.add_format(head)
    header_red = workbook.add_format({**head, "font_color": "#FF0000"})
    star = workbook.add_format({"font_name": "Arial", "font_size": 10, "bold": True, "font_color": "#FF0000"})
    star_title = workbook.add_format({"font_name": "Arial", "font_size": 10, "bold": True})
    text = workbook.add_format({**base, "num_format": "@"})
    number = workbook.add_format({**base, "num_format": "General"})
    cell = workbook.add_format({**base, "text_wrap": True, "border": 1, "border_color": TEMPLATE_BORDER_COLOR})
    cell_center = workbook.add_format({**base, "text_wrap": True, "border": 1, "border_color": TEMPLATE_BORDER_COLOR, "align": "center"})
    bold = workbook.add_format({**base, "bold": True})
    bold_cell = workbook.add_format({**base, "bold": True, "border": 1, "border_color": TEMPLATE_BORDER_COLOR})
    title = workbook.add_format({**base, "bold": True, "font_size": 14})
    note_number = workbook.add_format(
        {**base, "border": 1, "border_color": TEMPLATE_BORDER_COLOR, "align": "center", "valign": "vcenter"}
    )
    note_cell = workbook.add_format(
        {**base, "text_wrap": True, "border": 1, "border_color": TEMPLATE_BORDER_COLOR, "valign": "vcenter"}
    )
    sample_cell = workbook.add_format(
        {**base, "text_wrap": True, "border": 1, "border_color": TEMPLATE_BORDER_COLOR, "align": "left"}
    )
    last = len(names) - 1  # last column of the tables of the guide

    def write_header(sheet: Any, row: int, col: int, name: str) -> None:
        """Column name, with a red * when the column is required."""
        if name in required:
            sheet.write_rich_string(row, col, star_title, name, star, "*", header)
        else:
            sheet.write_string(row, col, name, header)

    sheet = workbook.add_worksheet("Template")
    for col, name in enumerate(names):
        is_number = name in handler.template_number_columns
        sheet.set_column(col, col, max(len(name) + 6, 16), number if is_number else text)
        write_header(sheet, 0, col, name)
    sheet.set_row(0, 22)
    sheet.freeze_panes(1, 0)
    # Sample rows (to be replaced by the user's data)
    for i, sample in enumerate(handler.template_sample_rows, start=1):
        for col, value in enumerate(sample):
            if names[col] in handler.template_number_columns:
                sheet.write_number(i, col, float(value), number)
            else:
                sheet.write_string(i, col, value, text)

    for lang in ("vi", "en"):
        words = TEMPLATE_TEXT[lang]
        descriptions = (
            handler.template_descriptions_vi
            if lang == "vi" and handler.template_descriptions_vi
            else handler.template_descriptions
        )
        guide = workbook.add_worksheet(words["sheet"])
        # Same width for every column: the tables of the guide line up
        guide.set_column(0, last, 24)
        guide.write_string(0, 0, words["template"].format(label=handler.label), title)
        notes = words["notes"]
        for i, note in enumerate(notes, start=2):
            guide.write_string(i, 0, f"{i - 1}.", note_number)
            guide.merge_range(i, 1, i, last, note, note_cell)
            guide.set_row(i, 32 if len(note) > 150 else 22)
        row = len(notes) + 3
        column_label, required_label, description_label = words["headers"]
        guide.write_string(row, 0, column_label, header)
        guide.write_string(row, 1, required_label, header)
        # the header covers the same columns as the descriptions below it
        guide.merge_range(row, 2, row, last, description_label, header)
        for i, name in enumerate(names, start=row + 1):
            guide.write_string(i, 0, name, bold_cell)
            is_required = name in required
            guide.write_string(
                i, 1, words["yes"] if is_required else words["no"],
                cell_center,
            )
            guide.merge_range(i, 2, i, last, descriptions.get(name, ""), cell)
            guide.set_row(i, 30 if len(descriptions.get(name, "")) > 120 else 18)
        row = row + len(names) + 3
        guide.write_string(row, 0, words["sample"], bold)
        for col, name in enumerate(names):
            write_header(guide, row + 1, col, name)
        for i, sample in enumerate(handler.template_sample_rows, start=row + 2):
            for col, value in enumerate(sample):
                if names[col] in handler.template_number_columns:
                    guide.write_number(i, col, float(value), sample_cell)
                else:
                    guide.write_string(i, col, value, sample_cell)
            guide.set_row(i, 30)
    workbook.close()
    return buffer.getvalue()
