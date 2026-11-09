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

from superset.upload_file.handlers.base import ProcessResult

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


def build_csv(result: ProcessResult) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(
        buffer, delimiter=CSV_DELIMITER, lineterminator=CSV_LINE_TERMINATOR
    )
    writer.writerow(result.columns)
    writer.writerows(result.rows)
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
    sheet.freeze_panes(1, 0)
    sheet.autofilter(0, 0, len(result.rows), len(result.columns) - 1)
    workbook.close()
    return buffer.getvalue()
