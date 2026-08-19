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
"""Headless per-chart capture for server-side dashboard exports.

The browser-based export (DownloadWord.tsx) captures one image per chart and
matches it to a ``{{ Chart Name }}`` placeholder. This module reproduces that
server-side so an automated caller does not need a browser, walking dashboard
tabs the same way so charts on inactive tabs are included.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

from flask import current_app
from flask_appbuilder.security.sqla.models import User

from superset.utils.urls import modify_url_query
from superset.utils.webdriver import DashboardStandaloneMode

logger = logging.getLogger(__name__)

CHART_NAME_SELECTOR = "[data-test-chart-name]"
CHART_HOLDER_ANCESTOR = (
    "xpath=ancestor::*[contains(@class, 'dashboard-component-chart-holder')][1]"
)
KPI_CHART_SELECTOR = '[data-kpi-line-chart="true"]'
TAB_BUTTON_SELECTOR = ".dashboard-component-tabs .ant-tabs-tab-btn"
# KPI charts restyle themselves while this class is on <body> (KpiLineChart.tsx)
CAPTURE_CLASS = "superset-word-export-capturing"
MAX_TAB_STEPS = 100


def _wait_for_charts(page: Any) -> None:
    """Wait for charts to finish drawing, mirroring WebDriverPlaywright."""
    locate_wait = current_app.config["SCREENSHOT_LOCATE_WAIT"] * 1000
    load_wait = current_app.config["SCREENSHOT_LOAD_WAIT"] * 1000

    try:
        page.locator(".chart-container").first.wait_for(
            state="visible", timeout=locate_wait
        )
    except Exception:  # pylint: disable=broad-except
        logger.warning("No chart container became visible before the timeout")

    try:
        page.locator(".loading").first.wait_for(state="detached", timeout=load_wait)
    except Exception:  # pylint: disable=broad-except
        logger.debug("No loading indicator to wait for")

    page.wait_for_timeout(
        current_app.config["SCREENSHOT_SELENIUM_ANIMATION_WAIT"] * 1000
    )


def _capture_visible_charts(page: Any, charts: dict[str, dict[str, Any]]) -> None:
    for index, element in enumerate(page.locator(CHART_NAME_SELECTOR).all()):
        name = element.get_attribute("data-test-chart-name")
        if not name or name in charts:
            continue

        # data-test-chart-name lives on .chart-slice INSIDE the holder, so the
        # holder is an ancestor; the frontend screenshots the holder.
        target = element.locator(CHART_HOLDER_ANCESTOR)
        if target.count() == 0:
            target = element

        try:
            if not target.is_visible():
                continue
            image = target.screenshot(type="png")
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed capturing chart %s", name)
            continue

        box = target.bounding_box() or {}
        charts[name] = {
            "image": f"data:image/png;base64,{base64.b64encode(image).decode()}",
            "name": name,
            "row": index,
            "col": 0,
            "width": round(box.get("width") or 0),
            "height": round(box.get("height") or 0),
        }


def _collect_kpi_statuses(page: Any, statuses: dict[str, dict[str, str]]) -> None:
    for element in page.locator(KPI_CHART_SELECTOR).all():
        try:
            if not element.is_visible():
                continue
            # Keyed like getKpiChartStatusKey in DownloadWord.tsx: charts sharing
            # a title must stay distinct or the counts come out short.
            key = element.evaluate(
                """node => [
                    node.closest('[data-test-chart-id]')
                        ?.getAttribute('data-test-chart-id') ?? '',
                    node.getAttribute('data-kpi-title') ?? '',
                    Array.from(document.querySelectorAll('*')).indexOf(node),
                ].join('|')"""
            )
            group = element.get_attribute("data-kpi-group") or "none"
            status = element.get_attribute("data-kpi-status") or "no_data"
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed reading KPI status attributes")
            continue

        statuses[key] = {"group": group, "status": status}


def _tab_key(button: Any, index: int) -> str:
    try:
        return f"{index}|{(button.text_content() or '').strip()}"
    except Exception:  # pylint: disable=broad-except
        return str(index)


def _is_active(button: Any) -> bool:
    try:
        classes = button.evaluate(
            "node => node.closest('.ant-tabs-tab')?.className || ''"
        )
        return "ant-tabs-tab-active" in classes
    except Exception:  # pylint: disable=broad-except
        return False


def capture_dashboard_charts(
    dashboard_url: str,
    user: User,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Capture one PNG per chart plus KPI statuses, walking every tab.

    Returns ``(charts, kpi_statuses)`` where each chart dict matches the payload
    the frontend posts, so ``word_export`` consumes it unchanged.
    """
    # Imported lazily: playwright is an optional dependency.
    from playwright.sync_api import (  # pylint: disable=import-outside-toplevel
        sync_playwright,
    )

    from superset.utils.machine_auth import (  # pylint: disable=import-outside-toplevel
        machine_auth_provider_factory,
    )

    url = modify_url_query(
        dashboard_url,
        standalone=DashboardStandaloneMode.REPORT.value,
    )
    window = current_app.config["WEBDRIVER_WINDOW"]["dashboard"]
    charts: dict[str, dict[str, Any]] = {}
    kpi_statuses: dict[str, dict[str, str]] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=current_app.config["WEBDRIVER_OPTION_ARGS"]
        )
        context = browser.new_context(
            bypass_csp=True,
            viewport={"width": window[0], "height": window[1]},
            device_scale_factor=current_app.config["WEBDRIVER_WINDOW"].get(
                "pixel_density", 1
            ),
        )
        context.set_default_timeout(
            current_app.config["SCREENSHOT_PLAYWRIGHT_DEFAULT_TIMEOUT"]
        )
        machine_auth_provider_factory.instance.authenticate_browser_context(
            context, user
        )
        page = context.new_page()

        try:
            page.goto(
                url,
                wait_until=current_app.config["SCREENSHOT_PLAYWRIGHT_WAIT_EVENT"],
            )
            page.evaluate(
                "cls => document.body.classList.add(cls)",
                CAPTURE_CLASS,
            )
            _wait_for_charts(page)
            _capture_visible_charts(page, charts)
            _collect_kpi_statuses(page, kpi_statuses)

            visited: set[str] = set()
            for _ in range(MAX_TAB_STEPS):
                buttons = page.locator(TAB_BUTTON_SELECTOR).all()
                next_button = None
                for index, button in enumerate(buttons):
                    key = _tab_key(button, index)
                    if _is_active(button):
                        visited.add(key)
                    elif key not in visited:
                        next_button = (key, button)
                        break

                if not next_button:
                    break

                key, button = next_button
                visited.add(key)
                button.click()
                _wait_for_charts(page)
                _capture_visible_charts(page, charts)
                _collect_kpi_statuses(page, kpi_statuses)
        finally:
            browser.close()

    logger.info(
        "Captured %d charts and %d KPI statuses from %s",
        len(charts),
        len(kpi_statuses),
        url,
    )
    return list(charts.values()), list(kpi_statuses.values())
