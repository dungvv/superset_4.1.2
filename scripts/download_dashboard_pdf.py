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
"""Login, ask for a dashboard PDF, wait for it, save it.

    export SUPERSET_URL=http://localhost:8088
    export SUPERSET_USERNAME=admin
    export SUPERSET_PASSWORD=admin
    download_dashboard_pdf.py 1 bao_cao.pdf

Period maths and the 10-param URL contract are imported from
export_dashboard_report rather than repeated here: send fewer than all 10 and
the time-filter plugin reloads the page mid-capture, exporting the wrong period.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date

from export_dashboard_report import (
    SupersetReportClient,
    build_url_params,
    resolve_comparison,
    resolve_period,
)

logger = logging.getLogger("download_pdf")


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    dashboard = argv[1] if len(argv) > 1 else os.environ.get("DASHBOARD_ID", "1")
    out_path = argv[2] if len(argv) > 2 else "dashboard.pdf"
    grain = os.environ.get("REPORT_GRAIN", "day")

    try:
        base_url = os.environ["SUPERSET_URL"]
        username = os.environ["SUPERSET_USERNAME"]
        password = os.environ["SUPERSET_PASSWORD"]
    except KeyError as ex:
        logger.error("missing env var %s", ex)
        return 2

    # 1. Login -> JWT, kept on the session's Authorization header.
    client = SupersetReportClient(base_url, username, password)

    # 2. Ask for the report over the most recent complete period.
    start, end = resolve_period(grain, date.today())
    comp_start, comp_end = resolve_comparison(grain, start, end)
    logger.info("Period %s..%s vs %s..%s", start, end, comp_start, comp_end)
    cache_key = client.request_export(
        dashboard, "pdf", build_url_params(grain, start, end, comp_start, comp_end)
    )

    # 3. Poll until the Celery worker finishes rendering.
    content, filename = client.wait_for_export(dashboard, cache_key)

    # 4. Save. Checked because a proxy sitting in front of Superset can answer
    # 200 with an HTML login page, which would otherwise be saved as ".pdf".
    if not content.startswith(b"%PDF"):
        logger.error("not a PDF (starts with %r), refusing to save", content[:20])
        return 1
    with open(out_path, "wb") as handle:
        handle.write(content)
    logger.info("Saved %s (%d bytes, server name %s)", out_path, len(content), filename)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
