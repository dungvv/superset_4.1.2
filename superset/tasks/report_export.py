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
"""Async generation of dashboard Word/PDF reports for external callers."""

import logging
from typing import Any, Optional

from flask import current_app

from superset import security_manager, thumbnail_cache
from superset.extensions import celery_app
from superset.tasks.utils import get_executor
from superset.utils.core import override_user

logger = logging.getLogger(__name__)

# Cached payloads carry a status so a poller can tell "still working" from
# "failed" without a second store.
STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"


def report_cache_key(dashboard_id: int, digest: str, export_format: str) -> str:
    return f"dashboard_report/{dashboard_id}/{export_format}/{digest}"


def set_report_state(
    cache_key: str,
    status: str,
    content: Optional[bytes] = None,
    filename: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if not thumbnail_cache:
        logger.warning("No thumbnail cache configured, cannot store report state")
        return

    thumbnail_cache.set(
        cache_key,
        {
            "status": status,
            "content": content,
            "filename": filename,
            "error": error,
        },
        timeout=current_app.config.get("WORD_EXPORT_CACHE_TIMEOUT", 3600),
    )


@celery_app.task(name="generate_dashboard_report", soft_time_limit=1800)
def generate_dashboard_report(  # pylint: disable=too-many-locals
    dashboard_id: int,
    dashboard_url: str,
    cache_key: str,
    export_format: str = "docx",
    template_context: Optional[dict[str, Any]] = None,
    username: Optional[str] = None,
) -> None:
    # pylint: disable=import-outside-toplevel
    from superset.dashboards.report_context import build_kpi_export_counts
    from superset.dashboards.report_screenshot import capture_dashboard_charts
    from superset.dashboards.word_export import (
        build_default_word_document,
        build_template_word_document,
        is_template_dashboard,
    )
    from superset.models.dashboard import Dashboard
    from superset.utils.pdf import convert_docx_to_pdf

    if not thumbnail_cache:
        logger.warning("No cache set, refusing to generate report")
        return

    try:
        dashboard = Dashboard.get(dashboard_id)
        _, exec_username = get_executor(
            executor_types=current_app.config["THUMBNAIL_EXECUTE_AS"],
            model=dashboard,
            current_user=username,
        )
        user = security_manager.find_user(exec_username)

        with override_user(user):
            charts, kpi_statuses = capture_dashboard_charts(dashboard_url, user)

        if not charts:
            raise ValueError(f"No charts captured from {dashboard_url}")

        context = dict(template_context or {})
        # Counts scraped from the rendered DOM, unless the caller supplied them.
        if not context.get("kpi_total"):
            context.update(build_kpi_export_counts(kpi_statuses))

        if is_template_dashboard(
            dashboard.id,
            dashboard.slug,
            dashboard.dashboard_title,
            current_app.config.get("WORD_EXPORT_TEMPLATE_DASHBOARDS", ()),
        ):
            time_grain = (template_context or {}).get("time_grain", "")
            template_by_grain = current_app.config.get(
                "WORD_EXPORT_TEMPLATE_BY_TIME_GRAIN",
                {},
            )
            default_template = current_app.config.get(
                "WORD_EXPORT_TEMPLATE_PATH",
                "TMPL_RP.docx",
            )
            template_path = template_by_grain.get(time_grain, default_template)
            output = build_template_word_document(
                charts,
                template_path,
                context,
            )
        else:
            output = build_default_word_document(charts, dashboard.dashboard_title)

        base_name = (dashboard.dashboard_title or "Dashboard").replace(" ", "_")
        if export_format == "pdf":
            output = convert_docx_to_pdf(output)
            filename = f"{base_name}_export.pdf"
        else:
            filename = f"{base_name}_export.docx"

        set_report_state(cache_key, STATUS_READY, content=output, filename=filename)
        logger.info(
            "Generated %s report for dashboard %s (%d charts)",
            export_format,
            dashboard_id,
            len(charts),
        )
    except Exception as ex:  # pylint: disable=broad-except
        logger.exception("Failed generating dashboard report")
        set_report_state(cache_key, STATUS_FAILED, error=str(ex))
