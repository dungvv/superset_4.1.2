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
"""Report label logic shared with the frontend Word export.

Mirrors the helpers in DownloadWord.tsx so an external API caller does not have
to reimplement the Vietnamese label rules.
"""
from __future__ import annotations

import re
from typing import Any

ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# time_grain values that render a date range instead of a single end date
WEEK_LIKE_GRAINS = ("week", "custom")

REPORT_TYPE_BY_GRAIN = {
    "day": "NGÀY",
    "week": "TUẦN",
    "month": "THÁNG",
    "quarter": "QUÝ",
    "year": "NĂM",
    "custom": "TUẦN",
}

SUM_TYPE_BY_GRAIN = {
    "day": "THÁNG",
    "month": "THÁNG",
    "week": "TUẦN",
    "custom": "TUẦN",
    "quarter": "QUÝ",
    "year": "NĂM",
}

KPI_COUNT_KEYS = (
    "kpi_total",
    "kpi_common_total",
    "kpi_common_passed",
    "kpi_common_failed",
    "kpi_common_no_data",
    "kpi_common_not_passed",
    "kpi_common_passed_rate",
    "kpi_key_total",
    "kpi_key_passed",
    "kpi_key_failed",
    "kpi_key_no_data",
    "kpi_key_not_passed",
    "kpi_key_passed_rate",
    "kpi_total_passed",
    "kpi_total_not_passed",
)


def format_date_dmy(iso_date: str) -> str:
    if not iso_date or not ISO_DATE_PATTERN.match(iso_date):
        return iso_date or ""
    year, month, day = iso_date.split("-")
    return f"{day}/{month}/{year}"


def format_report_month(iso_date: str) -> str:
    if not iso_date or not ISO_DATE_PATTERN.match(iso_date):
        return ""
    year, month, _day = iso_date.split("-")
    return f"{month}/{year}"


def calculate_passed_rate(passed: int, total: int) -> str:
    if total <= 0:
        return "0"
    return f"{(passed / total) * 100:.2f}"


def build_report_date(time_grain: str, start_date: str, end_date: str) -> str:
    """week/custom -> ``start - end``, month -> ``MM/YYYY``, else the end date."""
    if time_grain in WEEK_LIKE_GRAINS:
        return f"{format_date_dmy(start_date)} - {format_date_dmy(end_date)}"
    if time_grain == "month":
        return format_report_month(start_date)
    return format_date_dmy(end_date)


def build_kpi_export_counts(
    kpi_charts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Aggregate per-chart KPI statuses into the template count placeholders.

    Each entry is ``{"group": "none"|"common"|"key", "status": "passed"|"failed"
    |"no_data"}``, matching the ``data-kpi-*`` attributes read from the DOM.
    """
    counts: dict[str, Any] = {key: 0 for key in KPI_COUNT_KEYS}
    counts["kpi_common_passed_rate"] = "0"
    counts["kpi_key_passed_rate"] = "0"

    for chart in kpi_charts or []:
        group = chart.get("group")
        if group not in ("common", "key"):
            continue

        status = chart.get("status")
        if status not in ("passed", "failed", "no_data"):
            status = "no_data"

        counts[f"kpi_{group}_total"] += 1
        counts[f"kpi_{group}_{status}"] += 1

    counts["kpi_common_not_passed"] = (
        counts["kpi_common_total"] - counts["kpi_common_passed"]
    )
    counts["kpi_key_not_passed"] = counts["kpi_key_total"] - counts["kpi_key_passed"]
    counts["kpi_total"] = counts["kpi_common_total"] + counts["kpi_key_total"]
    counts["kpi_total_passed"] = (
        counts["kpi_common_passed"] + counts["kpi_key_passed"]
    )
    counts["kpi_total_not_passed"] = (
        counts["kpi_common_not_passed"] + counts["kpi_key_not_passed"]
    )
    counts["kpi_common_passed_rate"] = calculate_passed_rate(
        counts["kpi_common_passed"], counts["kpi_common_total"]
    )
    counts["kpi_key_passed_rate"] = calculate_passed_rate(
        counts["kpi_key_passed"], counts["kpi_key_total"]
    )

    return counts


def build_template_context(
    time_grain: str,
    start_date: str,
    end_date: str,
    kpi_counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the docx placeholder context from an ISO date range.

    ``start_date``/``end_date`` are ISO (``YYYY-MM-DD``); output dates are
    ``DD/MM/YYYY`` to match what the frontend sends.
    """
    is_week_like = time_grain in WEEK_LIKE_GRAINS
    formatted_start = format_date_dmy(start_date)
    formatted_end = format_date_dmy(end_date)

    context: dict[str, Any] = {
        "start_date": formatted_start,
        "end_date": formatted_end,
        "current_start_date": formatted_start,
        "current_end_date": formatted_end,
        "report_type": REPORT_TYPE_BY_GRAIN.get(time_grain, ""),
        "sum_type": SUM_TYPE_BY_GRAIN.get(time_grain, ""),
        "report_date": build_report_date(time_grain, start_date, end_date),
        "_from": "TỪ " if is_week_like else "",
        "_start_date": f"{formatted_start} " if is_week_like else "",
        "report_month": format_report_month(start_date),
    }

    context.update(build_kpi_export_counts(None))
    for key, value in (kpi_counts or {}).items():
        if value is not None:
            context[key] = value

    return context


def _self_check() -> None:
    assert format_date_dmy("2026-08-04") == "04/08/2026"
    assert format_date_dmy("") == ""
    assert format_date_dmy("not-a-date") == "not-a-date"
    assert format_report_month("2026-08-04") == "08/2026"
    assert format_report_month("bad") == ""

    day = build_template_context("day", "2026-08-01", "2026-08-31")
    assert day["report_type"] == "NGÀY"
    assert day["sum_type"] == "THÁNG"
    assert day["report_date"] == "31/08/2026", day["report_date"]
    assert day["_from"] == ""
    assert day["_start_date"] == ""
    assert day["report_month"] == "08/2026"

    week = build_template_context("week", "2026-08-01", "2026-08-07")
    assert week["report_type"] == "TUẦN"
    assert week["report_date"] == "01/08/2026 - 07/08/2026"
    assert week["_from"] == "TỪ "
    assert week["_start_date"] == "01/08/2026 "

    custom = build_template_context("custom", "2026-08-01", "2026-08-07")
    assert custom["report_type"] == "TUẦN"
    assert custom["sum_type"] == "TUẦN"
    assert custom["report_date"] == week["report_date"]

    month = build_template_context("month", "2026-08-01", "2026-08-31")
    assert month["report_date"] == "08/2026", month["report_date"]
    assert month["report_type"] == "THÁNG"

    quarter = build_template_context("quarter", "2026-07-01", "2026-09-30")
    assert quarter["report_type"] == "QUÝ"
    assert quarter["report_date"] == "30/09/2026"

    assert build_template_context("bogus", "2026-08-01", "2026-08-02")["sum_type"] == ""

    # no KPI charts -> zeroed counts, rate is "0" not a division by zero
    assert day["kpi_total"] == 0
    assert day["kpi_common_passed_rate"] == "0"

    counts = build_kpi_export_counts(
        [
            {"group": "common", "status": "passed"},
            {"group": "common", "status": "failed"},
            {"group": "common", "status": "no_data"},
            {"group": "key", "status": "passed"},
            {"group": "key", "status": "passed"},
            {"group": "none", "status": "passed"},
            {"group": "key", "status": "bogus"},
        ]
    )
    assert counts["kpi_common_total"] == 3
    assert counts["kpi_common_passed"] == 1
    assert counts["kpi_common_not_passed"] == 2
    assert counts["kpi_common_passed_rate"] == "33.33", counts["kpi_common_passed_rate"]
    assert counts["kpi_key_total"] == 3
    assert counts["kpi_key_passed"] == 2
    assert counts["kpi_key_no_data"] == 1  # unknown status counted as no_data
    assert counts["kpi_key_passed_rate"] == "66.67"
    assert counts["kpi_total"] == 6
    assert counts["kpi_total_passed"] == 3
    assert counts["kpi_total_not_passed"] == 3

    # caller-supplied counts win over the zeroed defaults
    overridden = build_template_context(
        "day", "2026-08-01", "2026-08-31", {"kpi_total": 12}
    )
    assert overridden["kpi_total"] == 12

    print("report_context self-check passed")


if __name__ == "__main__":
    _self_check()
