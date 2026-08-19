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
"""Drive the dashboard's own "Download as Word" button, then convert to PDF.

Uses the real UI rather than an API: the docx is assembled client-side in
DownloadWord.tsx from per-chart screenshots, so there is no endpoint that
returns a finished report.

    SUPERSET_URL=http://localhost:8088 SUPERSET_USERNAME=admin \
    SUPERSET_PASSWORD=admin export_dashboard_word.py --dashboard 1

Period maths is imported from export_dashboard_report so the URL params match
what the time-filter plugin expects; sending fewer than all 10 makes the plugin
recompute and reload the page mid-export, producing the wrong period.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from export_dashboard_report import (
    build_url_params,
    resolve_comparison,
    resolve_period,
)

logger = logging.getLogger("dashboard_word")

# Selectors, all from the components they live in:
#   actions-trigger      PageHeaderWithActions/index.tsx:169
#   Download submenu     HeaderActionsDropdown/index.jsx:272
#   Download as Word     DownloadMenuItems/DownloadWord.tsx:596
ACTIONS_TRIGGER = '[data-test="actions-trigger"]'
CHART_HOLDER = ".dashboard-component-chart-holder"
# The docx is built in the page from canvas screenshots of every chart, so the
# export cannot start until the charts have actually drawn.
CHART_RENDER_TIMEOUT_MS = 180_000
DOWNLOAD_TIMEOUT_MS = 600_000


def login(page, base_url: str, username: str, password: str) -> None:
    page.goto(f"{base_url}/login/", wait_until="domcontentloaded")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click('input[type="submit"], button[type="submit"]')
    page.wait_for_load_state("networkidle")

    if "/login" in page.url:
        raise RuntimeError("login failed: still on the login page")
    logger.info("Logged in as %s", username)


def open_dashboard(page, base_url: str, dashboard: str, params: dict[str, str]) -> None:
    url = f"{base_url}/superset/dashboard/{dashboard}/?{urlencode(params)}"
    logger.info("Opening %s", url)
    page.goto(url, wait_until="domcontentloaded")

    page.wait_for_selector(CHART_HOLDER, timeout=CHART_RENDER_TIMEOUT_MS)
    # Charts render asynchronously after the holders appear; the loading
    # spinners detaching is the signal DownloadWord itself waits for.
    try:
        page.wait_for_selector(".loading", state="detached", timeout=CHART_RENDER_TIMEOUT_MS)
    except Exception:  # pylint: disable=broad-except
        logger.debug("No loading indicator present")
    page.wait_for_timeout(5_000)


def download_word(page, out_dir: Path, stem: str) -> Path:
    page.click(ACTIONS_TRIGGER)
    page.get_by_text("Download", exact=True).click()

    # Capturing every chart then zipping the docx takes a while on big
    # dashboards, so the download timeout is deliberately generous.
    with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as info:
        page.get_by_text("Download as Word", exact=True).click()
    download = info.value

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.docx"
    download.save_as(path)

    # A proxy in front of Superset can answer 200 with an HTML page; that would
    # otherwise be saved as a ".docx" that Word refuses to open. docx is a zip.
    with open(path, "rb") as handle:
        if handle.read(2) != b"PK":
            raise RuntimeError(f"{path} is not a .docx (no zip magic)")

    logger.info("Saved %s (%d bytes)", path, path.stat().st_size)
    return path


def convert_to_pdf(docx_path: Path, soffice: str) -> Path:
    """LibreOffice headless, to keep the TMPL_RP.docx layout."""
    subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(docx_path.parent),
            str(docx_path),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )

    pdf_path = docx_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise RuntimeError(f"{soffice} reported success but {pdf_path} is missing")
    logger.info("Converted %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
    return pdf_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("SUPERSET_URL"))
    parser.add_argument("--dashboard", default=os.environ.get("DASHBOARD_ID", "1"))
    parser.add_argument("--username", default=os.environ.get("SUPERSET_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("SUPERSET_PASSWORD"))
    parser.add_argument(
        "--grain",
        default="day",
        choices=("day", "week", "month", "quarter", "year", "custom"),
    )
    parser.add_argument("--start-date", help="ISO date, required for --grain custom")
    parser.add_argument("--end-date", help="ISO date, required for --grain custom")
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("REPORT_OUTPUT_DIR", "."),
    )
    parser.add_argument("--no-pdf", action="store_true", help="keep the .docx only")
    parser.add_argument(
        "--soffice",
        default=os.environ.get("WORD_EXPORT_SOFFICE_BINARY", "soffice"),
    )
    parser.add_argument("--headed", action="store_true", help="show the browser")

    args = parser.parse_args(argv)

    missing = [
        name for name in ("base_url", "username", "password") if not getattr(args, name)
    ]
    if missing:
        parser.error(f"missing required: {', '.join(missing)}")
    if args.grain == "custom" and not (args.start_date and args.end_date):
        parser.error("--grain custom requires --start-date and --end-date")

    return args


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = parse_args(argv)

    # Imported here so --help works without playwright installed.
    from playwright.sync_api import sync_playwright  # pylint: disable=import-outside-toplevel

    if args.grain == "custom":
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
    else:
        start, end = resolve_period(args.grain, date.today())
    comp_start, comp_end = resolve_comparison(args.grain, start, end)
    logger.info("Period %s..%s vs %s..%s", start, end, comp_start, comp_end)

    params = build_url_params(args.grain, start, end, comp_start, comp_end)
    base_url = args.base_url.rstrip("/")
    stem = f"dashboard_{args.dashboard}_{args.grain}_{end.isoformat()}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed)
        # accept_downloads is what makes expect_download work at all.
        context = browser.new_context(
            accept_downloads=True,
            viewport={"width": 1600, "height": 1200},
        )
        page = context.new_page()
        try:
            login(page, base_url, args.username, args.password)
            open_dashboard(page, base_url, args.dashboard, params)
            docx_path = download_word(page, Path(args.output_dir), stem)
        finally:
            browser.close()

    if not args.no_pdf:
        convert_to_pdf(docx_path, args.soffice)

    return 0


def _self_check() -> None:
    """Arg parsing and the period wiring; the browser part needs a live server."""
    args = parse_args(
        ["--base-url", "http://x", "--username", "u", "--password", "p"]
    )
    assert args.grain == "day" and args.dashboard == "1"

    # day grain must resolve to yesterday, which is what the 08:50 cron wants
    start, end = resolve_period("day", date(2026, 8, 5))
    assert end == date(2026, 8, 4), end

    # all 10 params, or the plugin reloads the page mid-export
    params = build_url_params("day", start, end, *resolve_comparison("day", start, end))
    assert len(params) == 10, params
    assert params["time_grain"] == "day"
    assert params["current_end_date"] == "2026-08-04"

    for argv, expected in (
        (["--grain", "custom"], "requires --start-date"),
        ([], "missing required"),
    ):
        try:
            parse_args(argv if "--grain" not in argv else argv + [
                "--base-url", "http://x", "--username", "u", "--password", "p",
            ])
        except SystemExit:
            pass
        else:
            raise AssertionError(f"expected a parser error for {argv} ({expected})")

    print("export_dashboard_word self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        sys.exit(main())
