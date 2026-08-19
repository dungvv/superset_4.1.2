#!/usr/bin/env bash
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#
# Cron wrapper for the dashboard report exporters.
#
# Which script runs is set by REPORT_SCRIPT (default export_dashboard_report.py,
# which talks to the API). Use export_dashboard_word.py to drive the dashboard's
# own "Download as Word" button with Playwright and convert the result to PDF.
#
# Credentials come from an env file, NOT the crontab (crontabs are world
# readable on most distros). Defaults to /etc/superset/report.env; override
# with REPORT_ENV_FILE.
#
#   # /etc/superset/report.env   (chmod 600, owned by the cron user)
#   SUPERSET_URL=https://superset.example.com
#   SUPERSET_USERNAME=report_bot
#   SUPERSET_PASSWORD=...
#   DASHBOARD_ID=1
#   SMTP_HOST=smtp.example.com
#   SMTP_PORT=587
#   SMTP_USER=report_bot@example.com
#   SMTP_PASSWORD=...
#   SMTP_FROM=report_bot@example.com
#   REPORT_RECIPIENTS=a@example.com,b@example.com
#   REPORT_OUTPUT_DIR=/var/lib/superset/reports
#
#   # crontab -e   (time is the cron user's local time)
#   50 8 * * *  /opt/superset/scripts/run_dashboard_report.sh --grain day
#
#   # ... or, for the Playwright/Word route:
#   50 8 * * *  REPORT_SCRIPT=export_dashboard_word.py \
#                 /opt/superset/scripts/run_dashboard_report.sh --grain day
#
# --grain day exports the most recent COMPLETE day (yesterday), so 08:50 is
# safely after the previous day closed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${REPORT_ENV_FILE:-/etc/superset/report.env}"
PYTHON_BIN="${REPORT_PYTHON:-python3}"
LOG_FILE="${REPORT_LOG_FILE:-/var/log/superset/dashboard_report.log}"
REPORT_SCRIPT="${REPORT_SCRIPT:-export_dashboard_report.py}"

if [[ -r "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
else
  echo "env file $ENV_FILE not readable" >&2
  exit 1
fi

mkdir -p "$(dirname "$LOG_FILE")"

# One lock per script + argument set, so the daily and monthly jobs don't block
# each other but a slow run never overlaps itself.
LOCK_FILE="/tmp/dashboard_report.$(echo "$REPORT_SCRIPT $*" | tr -cs 'a-zA-Z0-9' '_').lock"

exec >>"$LOG_FILE" 2>&1
echo "=== $(date '+%F %T') start: $REPORT_SCRIPT $* ==="

# flock -n: skip this run if the previous one is still going, rather than
# queueing up browsers until the box falls over. -E 99 makes "skipped"
# distinguishable from "the export itself failed" in the log.
status=0
flock -n -E 99 "$LOCK_FILE" \
  "$PYTHON_BIN" "$SCRIPT_DIR/$REPORT_SCRIPT" "$@" || status=$?

if [[ $status -eq 99 ]]; then
  echo "skipped: a previous run still holds $LOCK_FILE"
fi
echo "=== $(date '+%F %T') end: status=$status ==="
exit "$status"
