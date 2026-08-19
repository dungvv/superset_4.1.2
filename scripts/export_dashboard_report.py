#!/usr/bin/env python3
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
"""Export a Superset dashboard to Word/PDF and email it.

Meant for cron. Uses only the standard library plus ``requests``.

    export_dashboard_report.py --grain day --email a@b.com

The reporting period defaults to the most recent complete one for the grain
(yesterday for day, last month for month, ...), which is what a scheduled run
almost always wants.
"""
from __future__ import annotations

import argparse
import calendar
import logging
import mimetypes
import os
import smtplib
import ssl
import sys
import time
from datetime import date, timedelta
from email.message import EmailMessage
from typing import Any

import requests

logger = logging.getLogger("dashboard_report")

POLL_INTERVAL_SECONDS = 10
DEFAULT_POLL_TIMEOUT = 1800
REQUEST_TIMEOUT = 120


# --------------------------------------------------------------------------
# Period maths — mirrors TimeFilterChart.tsx so the dashboard renders the same
# period it would for a human clicking the filter.
# --------------------------------------------------------------------------
def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + (value.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def resolve_period(grain: str, today: date) -> tuple[date, date]:
    """Most recent COMPLETE period for the grain, as (start, end)."""
    if grain == "day":
        day = today - timedelta(days=1)
        return day.replace(day=1), day
    if grain == "week":
        # ISO week: previous Monday..Sunday
        end = today - timedelta(days=today.isoweekday())
        return end - timedelta(days=6), end
    if grain == "month":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if grain == "quarter":
        start_month = 3 * ((today.month - 1) // 3) + 1
        end = date(today.year, start_month, 1) - timedelta(days=1)
        q_start_month = 3 * ((end.month - 1) // 3) + 1
        return date(end.year, q_start_month, 1), end
    if grain == "year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    raise ValueError(f"unsupported grain {grain!r}")


def resolve_comparison(grain: str, start: date, end: date) -> tuple[date, date]:
    """Comparison period, matching computeComparisonDateBounds."""
    if grain == "day":
        prev_end = _add_months(end, -1)
        return prev_end.replace(day=1), prev_end
    if grain == "week":
        return start - timedelta(days=7), end - timedelta(days=7)
    if grain == "month":
        prev = _add_months(start, -1)
        return prev.replace(day=1), _month_end(prev.year, prev.month)
    if grain == "quarter":
        return _add_months(start, -3), start - timedelta(days=1)
    if grain == "year":
        return date(start.year - 1, 1, 1), date(start.year - 1, 12, 31)
    if grain == "custom":
        span = (end - start).days
        prev_end = start - timedelta(days=1)
        return prev_end - timedelta(days=span), prev_end
    raise ValueError(f"unsupported grain {grain!r}")


def _grain_value(grain: str, start: date, end: date) -> str:
    if grain == "day":
        return end.isoformat()
    if grain == "month":
        return f"{start.year}-{start.month:02d}"
    if grain == "quarter":
        return f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    if grain == "year":
        return str(start.year)
    return f"{start.isoformat()} : {end.isoformat()}"


def build_url_params(
    grain: str, start: date, end: date, comp_start: date, comp_end: date
) -> dict[str, str]:
    """All 10 params the time-filter plugin needs.

    If ANY is missing the plugin recomputes and calls window.location.assign,
    reloading the page mid-capture and producing the wrong period.
    """
    time_group = "month" if grain in ("quarter", "year") else (
        "week" if grain == "custom" else "day"
    )
    packed = "|".join(
        [
            start.isoformat(),
            end.isoformat(),
            comp_start.isoformat(),
            comp_end.isoformat(),
            time_group,
        ]
    )
    # current_time_range is end-exclusive, like buildTimeRangeFromBounds
    current_range = f"{start.isoformat()} : {(end + timedelta(days=1)).isoformat()}"
    comparison_range = (
        f"{comp_start.isoformat()} : {(comp_end + timedelta(days=1)).isoformat()}"
    )

    return {
        "time_grain": grain,
        "grain_value": _grain_value(grain, start, end),
        "time_range": packed,
        "current_time_range": current_range,
        "comparison_time_range": comparison_range,
        "current_start_date": start.isoformat(),
        "current_end_date": end.isoformat(),
        "comparison_start_date": comp_start.isoformat(),
        "comparison_end_date": comp_end.isoformat(),
        "time_group": time_group,
    }


# --------------------------------------------------------------------------
# Superset API
# --------------------------------------------------------------------------
class SupersetReportClient:
    def __init__(self, base_url: str, username: str, password: str, provider: str = "db"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._login(username, password, provider)

    def _login(self, username: str, password: str, provider: str) -> None:
        response = self.session.post(
            f"{self.base_url}/api/v1/security/login",
            json={
                "username": username,
                "password": password,
                "provider": provider,
                "refresh": False,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("login succeeded but returned no access_token")
        self.session.headers["Authorization"] = f"Bearer {token}"
        logger.info("Authenticated with Superset at %s", self.base_url)

    def request_export(
        self,
        dashboard_id: str,
        export_format: str,
        url_params: dict[str, str],
    ) -> str:
        payload: dict[str, Any] = {
            "format": export_format,
            "time_grain": url_params["time_grain"],
            "current_start_date": url_params["current_start_date"],
            "current_end_date": url_params["current_end_date"],
            "url_params": url_params,
        }
        response = self.session.post(
            f"{self.base_url}/api/v1/dashboard/{dashboard_id}/export_report/",
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        cache_key = response.json()["cache_key"]
        logger.info("Export accepted, cache_key=%s", cache_key)
        return cache_key

    def wait_for_export(
        self,
        dashboard_id: str,
        cache_key: str,
        timeout: int = DEFAULT_POLL_TIMEOUT,
    ) -> tuple[bytes, str]:
        url = (
            f"{self.base_url}/api/v1/dashboard/{dashboard_id}"
            f"/export_report/{cache_key}/"
        )
        deadline = time.monotonic() + timeout

        while True:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)

            if response.status_code == 200:
                filename = _filename_from_headers(response) or f"report_{cache_key}"
                logger.info("Report ready: %s (%d bytes)", filename, len(response.content))
                return response.content, filename

            if response.status_code != 202:
                raise RuntimeError(
                    f"export failed ({response.status_code}): {response.text[:500]}"
                )

            if time.monotonic() >= deadline:
                raise TimeoutError(f"report not ready after {timeout}s")

            logger.info("Still generating, retrying in %ds", POLL_INTERVAL_SECONDS)
            time.sleep(POLL_INTERVAL_SECONDS)


def _filename_from_headers(response: requests.Response) -> str | None:
    disposition = response.headers.get("Content-Disposition", "")
    for part in disposition.split(";"):
        part = part.strip()
        if part.startswith("filename="):
            return part[len("filename="):].strip('"') or None
    return None


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------
def send_email(  # pylint: disable=too-many-arguments
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    sender: str,
    recipients: list[str],
    subject: str,
    body: str,
    attachment: bytes,
    filename: str,
    use_tls: bool = True,
) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    guessed, _ = mimetypes.guess_type(filename)
    maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
    message.add_attachment(
        attachment, maintype=maintype, subtype=subtype, filename=filename
    )

    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as smtp:
            if username:
                smtp.login(username, password or "")
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=REQUEST_TIMEOUT) as smtp:
            if use_tls:
                smtp.starttls(context=ssl.create_default_context())
            if username:
                smtp.login(username, password or "")
            smtp.send_message(message)

    logger.info("Emailed %s to %s", filename, ", ".join(recipients))


# --------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a Superset dashboard and email it",
    )
    parser.add_argument("--base-url", default=os.environ.get("SUPERSET_URL"))
    parser.add_argument("--dashboard", default=os.environ.get("DASHBOARD_ID", "1"))
    parser.add_argument("--username", default=os.environ.get("SUPERSET_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("SUPERSET_PASSWORD"))
    parser.add_argument("--provider", default=os.environ.get("SUPERSET_PROVIDER", "db"))
    parser.add_argument(
        "--grain",
        default="day",
        choices=("day", "week", "month", "quarter", "year", "custom"),
    )
    parser.add_argument("--format", default="pdf", choices=("pdf", "docx"))
    parser.add_argument("--start-date", help="ISO date, required for --grain custom")
    parser.add_argument("--end-date", help="ISO date, required for --grain custom")
    parser.add_argument(
        "--email",
        action="append",
        default=[],
        help="Recipient; repeatable. Omit to only write the file.",
    )
    parser.add_argument("--subject")
    parser.add_argument("--output-dir", default=os.environ.get("REPORT_OUTPUT_DIR"))
    parser.add_argument("--timeout", type=int, default=DEFAULT_POLL_TIMEOUT)

    parser.add_argument("--smtp-host", default=os.environ.get("SMTP_HOST"))
    parser.add_argument(
        "--smtp-port", type=int, default=int(os.environ.get("SMTP_PORT", "587"))
    )
    parser.add_argument("--smtp-user", default=os.environ.get("SMTP_USER"))
    parser.add_argument("--smtp-password", default=os.environ.get("SMTP_PASSWORD"))
    parser.add_argument("--smtp-from", default=os.environ.get("SMTP_FROM"))
    parser.add_argument("--no-tls", action="store_true")

    args = parser.parse_args(argv)

    missing = [
        name
        for name in ("base_url", "username", "password")
        if not getattr(args, name)
    ]
    if missing:
        parser.error(f"missing required: {', '.join(missing)}")

    recipients = [
        stripped
        for entry in args.email
        for raw in entry.split(",")
        if (stripped := raw.strip())
    ]
    if not recipients and os.environ.get("REPORT_RECIPIENTS"):
        recipients = [
            address.strip()
            for address in os.environ["REPORT_RECIPIENTS"].split(",")
            if address.strip()
        ]
    args.email = recipients

    if recipients and not (args.smtp_host and args.smtp_from):
        parser.error("--smtp-host and --smtp-from are required when emailing")

    if args.grain == "custom" and not (args.start_date and args.end_date):
        parser.error("--grain custom requires --start-date and --end-date")

    if not recipients and not args.output_dir:
        parser.error("nothing to do: pass --email and/or --output-dir")

    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = parse_args(argv)

    if args.grain == "custom":
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
    else:
        start, end = resolve_period(args.grain, date.today())
    comp_start, comp_end = resolve_comparison(args.grain, start, end)

    logger.info(
        "Exporting dashboard %s (%s) for %s..%s vs %s..%s",
        args.dashboard,
        args.grain,
        start,
        end,
        comp_start,
        comp_end,
    )

    url_params = build_url_params(args.grain, start, end, comp_start, comp_end)

    try:
        client = SupersetReportClient(
            args.base_url, args.username, args.password, args.provider
        )
        cache_key = client.request_export(args.dashboard, args.format, url_params)
        content, filename = client.wait_for_export(
            args.dashboard, cache_key, args.timeout
        )
    except Exception:  # pylint: disable=broad-except
        logger.exception("Export failed")
        return 1

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        dated = f"{end.isoformat()}_{filename}"
        path = os.path.join(args.output_dir, dated)
        with open(path, "wb") as handle:
            handle.write(content)
        logger.info("Wrote %s", path)

    if args.email:
        subject = args.subject or f"Báo cáo dashboard {start} - {end}"
        try:
            send_email(
                host=args.smtp_host,
                port=args.smtp_port,
                username=args.smtp_user,
                password=args.smtp_password,
                sender=args.smtp_from,
                recipients=args.email,
                subject=subject,
                body=(
                    f"Báo cáo tự động cho kỳ {start} đến {end}.\n"
                    f"Kỳ so sánh: {comp_start} đến {comp_end}.\n"
                ),
                attachment=content,
                filename=filename,
                use_tls=not args.no_tls,
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception("Report generated but email failed")
            return 1

    return 0


def _self_check() -> None:
    """Period maths, checked against the plugin's rules."""
    # day: yesterday, month-to-date start; comparison is the same day last month
    start, end = resolve_period("day", date(2026, 8, 4))
    assert (start, end) == (date(2026, 8, 1), date(2026, 8, 3)), (start, end)
    assert resolve_comparison("day", start, end) == (
        date(2026, 7, 1),
        date(2026, 7, 3),
    )

    # month: previous whole month
    start, end = resolve_period("month", date(2026, 8, 4))
    assert (start, end) == (date(2026, 7, 1), date(2026, 7, 31)), (start, end)
    assert resolve_comparison("month", start, end) == (
        date(2026, 6, 1),
        date(2026, 6, 30),
    )

    # month across a year boundary
    start, end = resolve_period("month", date(2026, 1, 15))
    assert (start, end) == (date(2025, 12, 1), date(2025, 12, 31)), (start, end)

    # quarter: previous whole quarter
    start, end = resolve_period("quarter", date(2026, 8, 4))
    assert (start, end) == (date(2026, 4, 1), date(2026, 6, 30)), (start, end)
    assert resolve_comparison("quarter", start, end) == (
        date(2026, 1, 1),
        date(2026, 3, 31),
    )

    # year
    assert resolve_period("year", date(2026, 8, 4)) == (
        date(2025, 1, 1),
        date(2025, 12, 31),
    )

    # week: previous Mon..Sun. 2026-08-04 is a Tuesday -> Jul 27..Aug 2
    start, end = resolve_period("week", date(2026, 8, 4))
    assert start.isoweekday() == 1 and end.isoweekday() == 7, (start, end)
    assert (start, end) == (date(2026, 7, 27), date(2026, 8, 2)), (start, end)
    assert resolve_comparison("week", start, end) == (
        date(2026, 7, 20),
        date(2026, 7, 26),
    )

    # leap year February
    assert resolve_period("month", date(2024, 3, 5)) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
    )

    # all 10 params present, or the plugin reloads mid-capture
    params = build_url_params(
        "day", date(2026, 8, 1), date(2026, 8, 3), date(2026, 7, 1), date(2026, 7, 3)
    )
    required = {
        "time_grain",
        "grain_value",
        "time_range",
        "current_time_range",
        "comparison_time_range",
        "current_start_date",
        "current_end_date",
        "comparison_start_date",
        "comparison_end_date",
        "time_group",
    }
    assert required <= set(params), required - set(params)
    assert all(params[key] for key in required), params
    assert params["time_range"] == "2026-08-01|2026-08-03|2026-07-01|2026-07-03|day"
    # end date is exclusive in the range form
    assert params["current_time_range"] == "2026-08-01 : 2026-08-04"
    assert build_url_params(
        "quarter", date(2026, 4, 1), date(2026, 6, 30), date(2026, 1, 1),
        date(2026, 3, 31),
    )["time_group"] == "month"
    assert params["grain_value"] == "2026-08-03"

    print("export_dashboard_report self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        sys.exit(main())
