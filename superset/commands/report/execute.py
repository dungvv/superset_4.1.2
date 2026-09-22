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
import logging
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Iterator, Optional, Union
from uuid import UUID

import pandas as pd
from celery.exceptions import SoftTimeLimitExceeded

from superset import app, db, security_manager
from superset.commands.base import BaseCommand
from superset.commands.dashboard.permalink.create import CreateDashboardPermalinkCommand
from superset.commands.exceptions import CommandException, UpdateFailedError
from superset.commands.report.alert import AlertCommand
from superset.commands.report.exceptions import (
    ReportScheduleAlertGracePeriodError,
    ReportScheduleClientErrorsException,
    ReportScheduleCsvFailedError,
    ReportScheduleCsvTimeout,
    ReportScheduleDataFrameFailedError,
    ReportScheduleDataFrameTimeout,
    ReportScheduleExecuteUnexpectedError,
    ReportScheduleNotFoundError,
    ReportSchedulePreviousWorkingError,
    ReportScheduleScreenshotFailedError,
    ReportScheduleScreenshotTimeout,
    ReportScheduleStateNotFoundError,
    ReportScheduleSystemErrorsException,
    ReportScheduleUnexpectedError,
    ReportScheduleWorkingTimeoutError,
)
from superset.common.chart_data import ChartDataResultFormat, ChartDataResultType
from superset.daos.report import (
    REPORT_SCHEDULE_ERROR_NOTIFICATION_MARKER,
    ReportScheduleDAO,
)
from superset.errors import ErrorLevel, SupersetError, SupersetErrorType
from superset.exceptions import SupersetErrorsException, SupersetException
from superset.extensions import feature_flag_manager, machine_auth_provider_factory
from superset.reports.models import (
    ReportDataFormat,
    ReportExecutionLog,
    ReportRecipients,
    ReportRecipientType,
    ReportSchedule,
    ReportScheduleType,
    ReportSourceFormat,
    ReportState,
)
from superset.reports.notifications import create_notification
from superset.reports.notifications.base import NotificationContent
from superset.reports.notifications.exceptions import (
    NotificationError,
    NotificationParamException,
    SlackV1NotificationError,
)
from superset.tasks.utils import get_executor
from superset.utils import json
from superset.utils.core import FilterOperator, HeaderDataType, override_user
from superset.utils.csv import get_chart_csv_data, get_chart_dataframe
from superset.utils.decorators import logs_context, transaction
from superset.utils.pdf import build_pdf_from_screenshots
from superset.utils.screenshots import ChartScreenshot, DashboardScreenshot
from superset.utils.slack import get_channels_with_search, SlackChannelTypes
from superset.utils.urls import get_url_path

logger = logging.getLogger(__name__)


def _build_send_now_time_range(as_of_date: str) -> str:
    """Return a one-day TEMPORAL_RANGE value for the given YYYY-MM-DD date."""
    day = datetime.strptime(as_of_date[:10], "%Y-%m-%d").date()
    next_day = day + timedelta(days=1)
    return f"{day.isoformat()} : {next_day.isoformat()}"


def _is_relative_sql_clause(sql: str) -> bool:
    """Detect chart SQL filters that pin data to 'today/yesterday' windows."""
    text_sql = (sql or "").upper()
    markers = (
        "TRUNC(SYSDATE)",
        "SYSDATE",
        "CURRENT_DATE",
        "CURRENT_TIMESTAMP",
        "NOW()",
        "GETDATE()",
    )
    return any(marker in text_sql for marker in markers)


def _filter_keeps_for_send_now(flt: dict[str, Any], col: str) -> bool:
    """Keep non-temporal filters that are unrelated to the send-now date column."""
    subject = str(flt.get("col") or flt.get("subject") or "").casefold()
    op = flt.get("op") or flt.get("operator")
    if subject == col.casefold():
        return False
    if op == FilterOperator.TEMPORAL_RANGE.value:
        return False
    sql_expr = flt.get("sqlExpression") or ""
    if _is_relative_sql_clause(sql_expr):
        return False
    if col.casefold() in sql_expr.casefold():
        return False
    return True


def _oracle_send_now_where(col: str, day: str) -> str:
    """Oracle-safe one-day predicate using TO_DATE (avoids ORA-01861)."""
    next_day = (
        datetime.strptime(day, "%Y-%m-%d").date() + timedelta(days=1)
    ).isoformat()
    return (
        f"TRUNC({col}) >= TO_DATE('{day}', 'YYYY-MM-DD') "
        f"AND TRUNC({col}) < TO_DATE('{next_day}', 'YYYY-MM-DD')"
    )


def apply_send_now_to_query_context(
    query_context: dict[str, Any],
    as_of_date: str,
    filter_date: str,
    backend: Optional[str] = None,
) -> dict[str, Any]:
    """
    Force chart data to the selected as-of day.

    Oracle: use extras.where with TO_DATE (TEMPORAL_RANGE often emits string
    literals that raise ORA-01861). Other engines: TEMPORAL_RANGE.
    Also strips relative SQL filters such as CREATE_DATE >= TRUNC(SYSDATE)-2.
    """
    import re

    qc = deepcopy(query_context)
    day = as_of_date[:10]
    time_range = _build_send_now_time_range(day)
    col = filter_date.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", col):
        raise ValueError(f"Invalid filter_date column name: {col}")

    is_oracle = (backend or "").lower() == "oracle"
    oracle_where = _oracle_send_now_where(col, day) if is_oracle else None

    date_filter_temporal = {
        "col": col,
        "op": FilterOperator.TEMPORAL_RANGE.value,
        "val": time_range,
    }

    for query in qc.get("queries") or []:
        existing = query.get("filters") or []
        filters = [flt for flt in existing if _filter_keeps_for_send_now(flt, col)]
        if not is_oracle:
            filters.append(date_filter_temporal)
        query["filters"] = filters

        if is_oracle:
            # Avoid engine temporal path that emits 'YYYY-MM-DD HH:MI:SS.FF'
            # string literals without TO_DATE.
            query.pop("time_range", None)
            query.pop("granularity", None)
            query["from_dttm"] = None
            query["to_dttm"] = None
        else:
            query["time_range"] = time_range
            query["granularity"] = col

        extras = query.get("extras") or {}
        if not isinstance(extras, dict):
            extras = {}
        else:
            extras = dict(extras)
        extras.pop("relative_start", None)
        extras.pop("relative_end", None)
        existing_where = (extras.get("where") or "").strip()
        if existing_where and (
            _is_relative_sql_clause(existing_where)
            or col.casefold() in existing_where.casefold()
        ):
            existing_where = ""
        if oracle_where:
            extras["where"] = (
                f"({existing_where}) AND ({oracle_where})"
                if existing_where
                else oracle_where
            )
        else:
            extras["where"] = existing_where
        query["extras"] = extras

    form_data = qc.get("form_data") or {}
    if not isinstance(form_data, dict):
        form_data = {}
    else:
        form_data = dict(form_data)

    adhoc_filters = []
    for flt in form_data.get("adhoc_filters") or []:
        if not isinstance(flt, dict):
            continue
        mapped = {
            "col": flt.get("subject"),
            "op": flt.get("operator"),
            "subject": flt.get("subject"),
            "operator": flt.get("operator"),
            "sqlExpression": flt.get("sqlExpression"),
        }
        if _filter_keeps_for_send_now(mapped, col):
            adhoc_filters.append(flt)

    if is_oracle and oracle_where:
        adhoc_filters.append(
            {
                "clause": "WHERE",
                "expressionType": "SQL",
                "sqlExpression": oracle_where,
                "filterOptionName": f"send_now_oracle_{col}",
                "isExtra": False,
                "isNew": False,
            }
        )
    else:
        adhoc_filters.append(
            {
                "clause": "WHERE",
                "expressionType": "SIMPLE",
                "operator": FilterOperator.TEMPORAL_RANGE.value,
                "operatorId": FilterOperator.TEMPORAL_RANGE.value,
                "subject": col,
                "comparator": time_range,
                "filterOptionName": f"send_now_{col}",
                "isExtra": False,
                "isNew": False,
            }
        )
    form_data["adhoc_filters"] = adhoc_filters
    if is_oracle:
        form_data.pop("time_range", None)
        form_data.pop("granularity_sqla", None)
    else:
        form_data["time_range"] = time_range
        form_data["granularity_sqla"] = col
    form_data.pop("relative_start", None)
    form_data.pop("relative_end", None)
    qc["form_data"] = form_data
    qc["force"] = True
    return qc


def apply_send_now_to_chart_params(
    params: dict[str, Any],
    as_of_date: str,
    filter_date: str,
    backend: Optional[str] = None,
) -> dict[str, Any]:
    """Rewrite a chart's saved params (form_data) for Send now."""
    qc = apply_send_now_to_query_context(
        {"queries": [{}], "form_data": deepcopy(params)},
        as_of_date,
        filter_date,
        backend=backend,
    )
    form_data = qc.get("form_data")
    return form_data if isinstance(form_data, dict) else params


def _chart_db_backend(chart: Any) -> str:
    """Best-effort database backend for a Slice; default oracle-safe."""
    try:
        datasource = chart.datasource
        if datasource is not None and getattr(datasource, "database", None):
            backend = datasource.database.backend
            if backend:
                return str(backend)
    except Exception:  # pylint: disable=broad-except
        pass
    return "oracle"


def enforce_send_now_on_query_context(
    query_context: Any,
    as_of_date: str,
    filter_date: str,
    backend: Optional[str] = None,
) -> None:
    """
    Re-apply send-now constraints after ChartDataQueryContextSchema.load().
    """
    from superset.common.utils.time_range_utils import get_since_until_from_time_range

    day = as_of_date[:10]
    time_range = _build_send_now_time_range(day)
    col = filter_date.strip()
    is_oracle = (backend or "").lower() == "oracle"
    oracle_where = _oracle_send_now_where(col, day) if is_oracle else None
    from_dttm, to_dttm = get_since_until_from_time_range(time_range)

    query_context.force = True
    for query_object in query_context.queries:
        filters = [
            flt
            for flt in (query_object.filter or [])
            if _filter_keeps_for_send_now(flt, col)
        ]
        if is_oracle:
            query_object.time_range = None
            query_object.from_dttm = None
            query_object.to_dttm = None
            query_object.granularity = None
        else:
            query_object.time_range = time_range
            query_object.from_dttm = from_dttm
            query_object.to_dttm = to_dttm
            query_object.granularity = col
            filters.append(
                {
                    "col": col,
                    "op": FilterOperator.TEMPORAL_RANGE.value,
                    "val": time_range,
                }
            )
        query_object.filter = filters

        extras = dict(query_object.extras or {})
        existing_where = (extras.get("where") or "").strip()
        if existing_where and (
            _is_relative_sql_clause(existing_where)
            or col.casefold() in existing_where.casefold()
        ):
            existing_where = ""
        if oracle_where:
            extras["where"] = (
                f"({existing_where}) AND ({oracle_where})"
                if existing_where
                else oracle_where
            )
        else:
            extras["where"] = existing_where
        extras.pop("relative_start", None)
        extras.pop("relative_end", None)
        query_object.extras = extras



class BaseReportState:
    current_states: list[ReportState] = []
    initial: bool = False

    @logs_context()
    def __init__(
        self,
        report_schedule: ReportSchedule,
        scheduled_dttm: datetime,
        execution_id: UUID,
        as_of_date: Optional[str] = None,
        filter_date: Optional[str] = None,
    ) -> None:
        self._report_schedule = report_schedule
        self._scheduled_dttm = scheduled_dttm
        self._start_dttm = datetime.utcnow()
        self._execution_id = execution_id

        # Prefer explicit Celery kwargs; fall back to extra.send_now for audit path
        send_now = (report_schedule.extra or {}).get("send_now") or {}
        self._as_of_date = as_of_date or send_now.get("as_of_date")
        self._filter_date = filter_date or send_now.get("filter_date")
        if isinstance(self._as_of_date, str):
            self._as_of_date = self._as_of_date.strip() or None
        if isinstance(self._filter_date, str):
            self._filter_date = self._filter_date.strip() or None

    def _has_send_now_override(self) -> bool:
        return bool(self._as_of_date and self._filter_date)

    def _send_now_explore_form_data(self) -> dict[str, Any]:
        form_data: dict[str, Any] = {"slice_id": self._report_schedule.chart_id}
        chart = self._report_schedule.chart
        if chart and chart.params:
            try:
                saved = json.loads(chart.params)
                if isinstance(saved, dict):
                    form_data.update(saved)
                    form_data["slice_id"] = self._report_schedule.chart_id
            except (TypeError, json.JSONDecodeError):
                pass
        if not self._has_send_now_override():
            return form_data
        assert self._as_of_date and self._filter_date
        time_range = _build_send_now_time_range(self._as_of_date)
        col = self._filter_date
        adhoc_filters = []
        for flt in form_data.get("adhoc_filters") or []:
            if not isinstance(flt, dict):
                continue
            mapped = {
                "col": flt.get("subject"),
                "op": flt.get("operator"),
                "subject": flt.get("subject"),
                "operator": flt.get("operator"),
                "sqlExpression": flt.get("sqlExpression"),
            }
            if _filter_keeps_for_send_now(mapped, col):
                adhoc_filters.append(flt)
        adhoc_filters.append(
            {
                "clause": "WHERE",
                "expressionType": "SIMPLE",
                "operator": FilterOperator.TEMPORAL_RANGE.value,
                "operatorId": FilterOperator.TEMPORAL_RANGE.value,
                "subject": col,
                "comparator": time_range,
                "filterOptionName": f"send_now_{col}",
            }
        )
        form_data["adhoc_filters"] = adhoc_filters
        form_data["time_range"] = time_range
        form_data["granularity_sqla"] = col
        form_data.pop("relative_start", None)
        form_data.pop("relative_end", None)
        return form_data

    def _run_chart_data_with_send_now(
        self,
        result_format: ChartDataResultFormat,
    ) -> dict[str, Any]:
        """Execute chart query in-process with Send now date override."""
        from superset.charts.post_processing import apply_post_process
        from superset.charts.schemas import ChartDataQueryContextSchema
        from superset.commands.chart.data.get_data_command import ChartDataCommand

        chart = self._report_schedule.chart
        if not chart or not chart.query_context:
            raise ReportScheduleCsvFailedError(
                "Chart has no query context saved. Please open and save the chart."
            )
        assert self._as_of_date and self._filter_date
        backend = None
        try:
            datasource = chart.datasource
            if datasource is not None and getattr(datasource, "database", None):
                backend = datasource.database.backend
        except Exception:  # pylint: disable=broad-except
            backend = None
        # Product datasets are Oracle; default to oracle-safe path when unknown
        if not backend:
            backend = "oracle"
            logger.info(
                "Send now: datasource backend unknown, defaulting to oracle-safe filters"
            )

        qc_dict = apply_send_now_to_query_context(
            json.loads(chart.query_context),
            self._as_of_date,
            self._filter_date,
            backend=backend,
        )
        qc_dict["result_format"] = result_format
        qc_dict["result_type"] = ChartDataResultType.POST_PROCESSED
        qc_dict["force"] = True

        query_context = ChartDataQueryContextSchema().load(qc_dict)
        enforce_send_now_on_query_context(
            query_context,
            self._as_of_date,
            self._filter_date,
            backend=backend,
        )
        command = ChartDataCommand(query_context)
        command.validate()
        result = command.run()

        # Log generated SQL so we can verify the date filter landed
        for idx, query in enumerate(result.get("queries") or []):
            logger.info(
                "Send now query[%s] as_of=%s filter_date=%s sql=%s",
                idx,
                self._as_of_date,
                self._filter_date,
                (query.get("query") or "")[:2000],
            )

        try:
            form_data = json.loads(chart.params) if chart.params else {}
        except (TypeError, json.JSONDecodeError):
            form_data = {}
        if not isinstance(form_data, dict):
            form_data = {}
        form_data.update(qc_dict.get("form_data") or {})
        result = apply_post_process(
            result, form_data, query_context.datasource
        )
        return result

    @contextmanager
    def _temporary_chart_query_context(self) -> Iterator[None]:
        """
        Temporarily rewrite chart.query_context for Send now data pulls.
        Restores the original context afterwards so cron stays unchanged.
        """
        chart = self._report_schedule.chart
        if not chart or not self._has_send_now_override():
            yield
            return

        assert self._as_of_date and self._filter_date
        original_qc = chart.query_context
        original_params = chart.params
        backend = _chart_db_backend(chart)
        try:
            if not original_qc:
                yield
                return
            qc_dict = json.loads(original_qc)
            patched = apply_send_now_to_query_context(
                qc_dict,
                self._as_of_date,
                self._filter_date,
                backend=backend,
            )
            chart.query_context = json.dumps(patched)
            try:
                params = json.loads(original_params) if original_params else {}
            except (TypeError, json.JSONDecodeError):
                params = {}
            if isinstance(params, dict):
                form_data = patched.get("form_data") or {}
                params["adhoc_filters"] = form_data.get("adhoc_filters", [])
                if "time_range" in form_data:
                    params["time_range"] = form_data.get("time_range")
                else:
                    params.pop("time_range", None)
                if "granularity_sqla" in form_data:
                    params["granularity_sqla"] = form_data.get("granularity_sqla")
                else:
                    params.pop("granularity_sqla", None)
                params.pop("relative_start", None)
                params.pop("relative_end", None)
                chart.params = json.dumps(params)
            db.session.commit()
            logger.info(
                "Send now override applied: report=%s as_of=%s filter_date=%s",
                self._report_schedule.id,
                self._as_of_date,
                self._filter_date,
            )
            yield
        finally:
            chart.query_context = original_qc
            chart.params = original_params
            db.session.commit()

    @contextmanager
    def _temporary_dashboard_charts_send_now(self) -> Iterator[None]:
        """
        Temporarily rewrite every dashboard chart's params/query_context so
        Selenium screenshots honor Send now (permalink native filters alone
        are not enough — charts load their own saved relative filters).
        Restores originals afterwards so scheduled runs stay unchanged.
        """
        dashboard = self._report_schedule.dashboard
        if not dashboard or not self._has_send_now_override():
            yield
            return

        assert self._as_of_date and self._filter_date
        slices = list(dashboard.slices or [])
        originals: list[tuple[Any, Optional[str], Optional[str]]] = [
            (chart, chart.query_context, chart.params) for chart in slices
        ]
        patched = 0
        try:
            for chart in slices:
                backend = _chart_db_backend(chart)
                form_data: Optional[dict[str, Any]] = None

                if chart.query_context:
                    try:
                        qc_dict = json.loads(chart.query_context)
                        if isinstance(qc_dict, dict):
                            patched_qc = apply_send_now_to_query_context(
                                qc_dict,
                                self._as_of_date,
                                self._filter_date,
                                backend=backend,
                            )
                            chart.query_context = json.dumps(patched_qc)
                            fd = patched_qc.get("form_data")
                            if isinstance(fd, dict):
                                form_data = fd
                    except (TypeError, json.JSONDecodeError, ValueError) as ex:
                        logger.warning(
                            "Send now dashboard: skip query_context patch "
                            "slice_id=%s: %s",
                            chart.id,
                            ex,
                        )

                try:
                    params = json.loads(chart.params) if chart.params else {}
                except (TypeError, json.JSONDecodeError):
                    params = {}
                if not isinstance(params, dict):
                    params = {}

                if form_data is not None:
                    params["adhoc_filters"] = form_data.get("adhoc_filters", [])
                    if "time_range" in form_data:
                        params["time_range"] = form_data.get("time_range")
                    else:
                        params.pop("time_range", None)
                    if "granularity_sqla" in form_data:
                        params["granularity_sqla"] = form_data.get(
                            "granularity_sqla"
                        )
                    else:
                        params.pop("granularity_sqla", None)
                    params.pop("relative_start", None)
                    params.pop("relative_end", None)
                else:
                    try:
                        params = apply_send_now_to_chart_params(
                            params,
                            self._as_of_date,
                            self._filter_date,
                            backend=backend,
                        )
                    except ValueError as ex:
                        logger.warning(
                            "Send now dashboard: skip params patch "
                            "slice_id=%s: %s",
                            chart.id,
                            ex,
                        )
                        continue

                params["force"] = True
                chart.params = json.dumps(params)
                patched += 1

            db.session.commit()
            logger.info(
                "Send now dashboard charts patched: report=%s dashboard=%s "
                "as_of=%s filter_date=%s charts=%s/%s",
                self._report_schedule.id,
                dashboard.id,
                self._as_of_date,
                self._filter_date,
                patched,
                len(slices),
            )
            yield
        finally:
            for chart, original_qc, original_params in originals:
                chart.query_context = original_qc
                chart.params = original_params
            db.session.commit()

    def update_report_schedule_and_log(
        self,
        state: ReportState,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Update the report schedule state et al. and reflect the change in the execution
        log.
        """
        self.update_report_schedule(state)
        self.create_log(error_message)

    def update_report_schedule(self, state: ReportState) -> None:
        """
        Update the report schedule state et al.

        When the report state is WORKING we must ensure that the values from the last
        execution run are cleared to ensure that they are not propagated to the
        execution log.
        """

        if state == ReportState.WORKING:
            self._report_schedule.last_value = None
            self._report_schedule.last_value_row_json = None

        self._report_schedule.last_state = state
        self._report_schedule.last_eval_dttm = datetime.utcnow()

    def update_report_schedule_slack_v2(self) -> None:
        """
        Update the report schedule type and channels for all slack recipients to v2.
        V2 uses ids instead of names for channels.
        """
        try:
            for recipient in self._report_schedule.recipients:
                if recipient.type == ReportRecipientType.SLACK:
                    recipient.type = ReportRecipientType.SLACKV2
                    slack_recipients = json.loads(recipient.recipient_config_json)
                    # we need to ensure that existing reports can also fetch
                    # ids from private channels
                    recipient.recipient_config_json = json.dumps(
                        {
                            "target": get_channels_with_search(
                                slack_recipients["target"],
                                types=[
                                    SlackChannelTypes.PRIVATE,
                                    SlackChannelTypes.PUBLIC,
                                ],
                            )
                        }
                    )
        except Exception as ex:
            logger.warning(
                "Failed to update slack recipients to v2: %s", str(ex), exc_info=True
            )
            raise UpdateFailedError from ex

    def create_log(self, error_message: Optional[str] = None) -> None:
        """
        Creates a Report execution log, uses the current computed last_value for Alerts
        """
        log = ReportExecutionLog(
            scheduled_dttm=self._scheduled_dttm,
            start_dttm=self._start_dttm,
            end_dttm=datetime.utcnow(),
            value=self._report_schedule.last_value,
            value_row_json=self._report_schedule.last_value_row_json,
            state=self._report_schedule.last_state,
            error_message=error_message,
            report_schedule=self._report_schedule,
            uuid=self._execution_id,
        )
        db.session.add(log)
        db.session.commit()  # pylint: disable=consider-using-transaction

    def _build_send_now_dashboard_state(self) -> dict[str, Any]:
        """
        Build permalink state so dashboard screenshots apply the Send now date
        via native filters that target filter_date (or global time filters).

        Oracle: avoid TEMPORAL_RANGE / time_range in dataMask (ORA-01861);
        clear global time filters and inject TO_DATE via adhoc SQL instead.
        Chart params are also temporarily patched in
        _temporary_dashboard_charts_send_now.
        """
        assert self._as_of_date and self._filter_date
        dashboard = self._report_schedule.dashboard
        day = self._as_of_date[:10]
        time_range = _build_send_now_time_range(day)
        col = self._filter_date.strip()

        is_oracle = False
        try:
            for chart in dashboard.slices or []:
                if _chart_db_backend(chart).lower() == "oracle":
                    is_oracle = True
                    break
        except Exception:  # pylint: disable=broad-except
            is_oracle = True

        base_state: dict[str, Any] = {}
        existing = (self._report_schedule.extra or {}).get("dashboard")
        if isinstance(existing, dict):
            base_state = dict(existing)

        data_mask: dict[str, Any] = dict(base_state.get("dataMask") or {})

        try:
            metadata = json.loads(dashboard.json_metadata or "{}")
        except (TypeError, json.JSONDecodeError):
            metadata = {}

        native_filters = metadata.get("native_filter_configuration") or []
        matched = 0
        oracle_where = _oracle_send_now_where(col, day) if is_oracle else None

        for native_filter in native_filters:
            if not isinstance(native_filter, dict):
                continue
            filter_id = native_filter.get("id")
            if not filter_id:
                continue
            filter_type = native_filter.get("filterType") or ""
            targets = native_filter.get("targets") or []

            # Global dashboard time filter
            if filter_type == "filter_time":
                if is_oracle:
                    # Clear so it doesn't emit Oracle-unsafe temporal literals;
                    # chart-level TO_DATE patch supplies the date window.
                    data_mask[filter_id] = {
                        "id": filter_id,
                        "extraFormData": {},
                        "filterState": {"value": None},
                    }
                else:
                    data_mask[filter_id] = {
                        "id": filter_id,
                        "extraFormData": {"time_range": time_range},
                        "filterState": {"value": time_range},
                    }
                matched += 1
                continue

            # Filters bound to the send-now date column
            for target in targets:
                if not isinstance(target, dict):
                    continue
                column = target.get("column") or {}
                if not isinstance(column, dict):
                    continue
                col_name = column.get("name") or column.get("column_name") or ""
                if col_name.casefold() != col.casefold():
                    continue
                if is_oracle and oracle_where:
                    data_mask[filter_id] = {
                        "id": filter_id,
                        "extraFormData": {
                            "adhoc_filters": [
                                {
                                    "clause": "WHERE",
                                    "expressionType": "SQL",
                                    "sqlExpression": oracle_where,
                                    "filterOptionName": f"send_now_oracle_{col_name}",
                                    "isExtra": True,
                                }
                            ],
                        },
                        "filterState": {
                            "value": time_range,
                            "label": time_range,
                        },
                    }
                else:
                    data_mask[filter_id] = {
                        "id": filter_id,
                        "extraFormData": {
                            "filters": [
                                {
                                    "col": col_name,
                                    "op": FilterOperator.TEMPORAL_RANGE.value,
                                    "val": time_range,
                                }
                            ],
                            "time_range": time_range,
                        },
                        "filterState": {
                            "value": time_range,
                            "label": time_range,
                        },
                    }
                matched += 1
                break

        if matched == 0:
            logger.warning(
                "Send now dashboard: no native filter matched column '%s' "
                "on dashboard_id=%s (filters=%s). Chart params patch still applied.",
                col,
                dashboard.id if dashboard else None,
                [
                    {
                        "id": nf.get("id"),
                        "type": nf.get("filterType"),
                        "targets": nf.get("targets"),
                    }
                    for nf in native_filters
                    if isinstance(nf, dict)
                ],
            )
        else:
            logger.info(
                "Send now dashboard override: report=%s dashboard=%s "
                "as_of=%s filter_date=%s matched_filters=%s oracle=%s",
                self._report_schedule.id,
                dashboard.id if dashboard else None,
                self._as_of_date,
                col,
                matched,
                is_oracle,
            )

        url_params = list(base_state.get("urlParams") or [])
        # Ensure force refresh so screenshot isn't served from stale cache
        if not any(param and param[0] == "force" for param in url_params):
            url_params.append(("force", "true"))

        return {
            **base_state,
            "dataMask": data_mask,
            "urlParams": url_params,
        }

    def _get_url(
        self,
        user_friendly: bool = False,
        result_format: Optional[ChartDataResultFormat] = None,
        **kwargs: Any,
    ) -> str:
        """
        Get the url for this report schedule: chart or dashboard
        """
        force = "true" if self._report_schedule.force_screenshot else "false"
        if self._report_schedule.chart:
            if result_format in {
                ChartDataResultFormat.CSV,
                ChartDataResultFormat.JSON,
            }:
                return get_url_path(
                    "ChartDataRestApi.get_data",
                    pk=self._report_schedule.chart_id,
                    format=result_format.value,
                    type=ChartDataResultType.POST_PROCESSED.value,
                    force=force,
                )
            return get_url_path(
                "ExploreView.root",
                user_friendly=user_friendly,
                form_data=json.dumps(self._send_now_explore_form_data()),
                force=force,
                **kwargs,
            )

        # Send now: render dashboard via permalink with injected date filters
        if self._has_send_now_override() and self._report_schedule.dashboard:
            state = self._build_send_now_dashboard_state()
            permalink_key = CreateDashboardPermalinkCommand(
                dashboard_id=str(self._report_schedule.dashboard.uuid),
                state=state,
            ).run()
            return get_url_path("Superset.dashboard_permalink", key=permalink_key)

        # If we need to render dashboard in a specific state, use stateful permalink
        if dashboard_state := self._report_schedule.extra.get("dashboard"):
            permalink_key = CreateDashboardPermalinkCommand(
                dashboard_id=str(self._report_schedule.dashboard.uuid),
                state=dashboard_state,
            ).run()
            return get_url_path("Superset.dashboard_permalink", key=permalink_key)

        dashboard = self._report_schedule.dashboard
        dashboard_id_or_slug = (
            dashboard.uuid if dashboard and dashboard.uuid else dashboard.id
        )
        return get_url_path(
            "Superset.dashboard",
            user_friendly=user_friendly,
            dashboard_id_or_slug=dashboard_id_or_slug,
            force=force,
            **kwargs,
        )

    def _get_screenshots(self) -> list[bytes]:
        """
        Get chart or dashboard screenshots
        :raises: ReportScheduleScreenshotFailedError
        """
        if self._has_send_now_override() and self._report_schedule.dashboard:
            logger.info(
                "Send now dashboard screenshot: report_id=%s as_of=%s filter_date=%s",
                self._report_schedule.id,
                self._as_of_date,
                self._filter_date,
            )

        with self._temporary_chart_query_context():
            with self._temporary_dashboard_charts_send_now():
                url = self._get_url()
                _, username = get_executor(
                    executor_types=app.config["ALERT_REPORTS_EXECUTE_AS"],
                    model=self._report_schedule,
                )
                user = security_manager.find_user(username)

                if self._report_schedule.chart:
                    window_width, window_height = app.config["WEBDRIVER_WINDOW"][
                        "slice"
                    ]
                    window_size = (
                        self._report_schedule.custom_width or window_width,
                        self._report_schedule.custom_height or window_height,
                    )
                    screenshot: Union[
                        ChartScreenshot, DashboardScreenshot
                    ] = ChartScreenshot(
                        url,
                        self._report_schedule.chart.digest,
                        window_size=window_size,
                        thumb_size=app.config["WEBDRIVER_WINDOW"]["slice"],
                    )
                else:
                    window_width, window_height = app.config["WEBDRIVER_WINDOW"][
                        "dashboard"
                    ]
                    window_size = (
                        self._report_schedule.custom_width or window_width,
                        self._report_schedule.custom_height or window_height,
                    )
                    screenshot = DashboardScreenshot(
                        url,
                        self._report_schedule.dashboard.digest,
                        window_size=window_size,
                        thumb_size=app.config["WEBDRIVER_WINDOW"]["dashboard"],
                    )
                try:
                    image = screenshot.get_screenshot(user=user)
                except SoftTimeLimitExceeded as ex:
                    logger.warning("A timeout occurred while taking a screenshot.")
                    raise ReportScheduleScreenshotTimeout() from ex
                except Exception as ex:
                    raise ReportScheduleScreenshotFailedError(
                        f"Failed taking a screenshot {str(ex)}"
                    ) from ex
                if not image:
                    raise ReportScheduleScreenshotFailedError()
                return [image]

    def _get_pdf(self) -> bytes:
        """
        Get chart or dashboard pdf
        :raises: ReportSchedulePdfFailedError
        """
        screenshots = self._get_screenshots()
        pdf = build_pdf_from_screenshots(screenshots)

        return pdf

    def _get_csv_data(self) -> bytes:
        if self._has_send_now_override() and self._report_schedule.chart:
            try:
                logger.info(
                    "Send now CSV in-process: report=%s as_of=%s filter_date=%s",
                    self._report_schedule.id,
                    self._as_of_date,
                    self._filter_date,
                )
                result = self._run_chart_data_with_send_now(ChartDataResultFormat.CSV)
                queries = result.get("queries") or []
                if not queries or queries[0].get("data") in (None, ""):
                    raise ReportScheduleCsvFailedError()
                data = queries[0]["data"]
                if isinstance(data, bytes):
                    return data
                if isinstance(data, str):
                    return data.encode("utf-8")
                raise ReportScheduleCsvFailedError(
                    f"Unexpected CSV payload type: {type(data)}"
                )
            except ReportScheduleCsvFailedError:
                raise
            except SoftTimeLimitExceeded as ex:
                raise ReportScheduleCsvTimeout() from ex
            except Exception as ex:
                raise ReportScheduleCsvFailedError(
                    f"Failed generating csv with send-now override: {ex}"
                ) from ex

        url = self._get_url(result_format=ChartDataResultFormat.CSV)
        _, username = get_executor(
            executor_types=app.config["ALERT_REPORTS_EXECUTE_AS"],
            model=self._report_schedule,
        )
        user = security_manager.find_user(username)
        auth_cookies = machine_auth_provider_factory.instance.get_auth_cookies(user)

        if self._report_schedule.chart.query_context is None:
            logger.warning("No query context found, taking a screenshot to generate it")
            self._update_query_context()

        try:
            logger.info("Getting chart from %s as user %s", url, user.username)
            csv_data = get_chart_csv_data(chart_url=url, auth_cookies=auth_cookies)
        except SoftTimeLimitExceeded as ex:
            raise ReportScheduleCsvTimeout() from ex
        except Exception as ex:
            raise ReportScheduleCsvFailedError(
                f"Failed generating csv {str(ex)}"
            ) from ex
        if not csv_data:
            raise ReportScheduleCsvFailedError()
        return csv_data

    def _get_embedded_data(self) -> pd.DataFrame:
        """
        Return data as a Pandas dataframe, to embed in notifications as a table.
        """
        if self._has_send_now_override() and self._report_schedule.chart:
            try:
                result = self._run_chart_data_with_send_now(ChartDataResultFormat.JSON)
                queries = result.get("queries") or []
                if not queries:
                    raise ReportScheduleCsvFailedError()
                data = queries[0].get("data")
                if data is None:
                    raise ReportScheduleCsvFailedError()
                df = pd.DataFrame.from_dict(data)
                if df.empty:
                    raise ReportScheduleCsvFailedError()
                return df
            except ReportScheduleCsvFailedError:
                raise
            except SoftTimeLimitExceeded as ex:
                raise ReportScheduleDataFrameTimeout() from ex
            except Exception as ex:
                raise ReportScheduleDataFrameFailedError(
                    f"Failed generating dataframe with send-now override: {ex}"
                ) from ex

        url = self._get_url(result_format=ChartDataResultFormat.JSON)
        _, username = get_executor(
            executor_types=app.config["ALERT_REPORTS_EXECUTE_AS"],
            model=self._report_schedule,
        )
        user = security_manager.find_user(username)
        auth_cookies = machine_auth_provider_factory.instance.get_auth_cookies(user)

        if self._report_schedule.chart.query_context is None:
            logger.warning("No query context found, taking a screenshot to generate it")
            self._update_query_context()

        try:
            logger.info("Getting chart from %s as user %s", url, user.username)
            dataframe = get_chart_dataframe(url, auth_cookies)
        except SoftTimeLimitExceeded as ex:
            raise ReportScheduleDataFrameTimeout() from ex
        except Exception as ex:
            raise ReportScheduleDataFrameFailedError(
                f"Failed generating dataframe {str(ex)}"
            ) from ex
        if dataframe is None:
            raise ReportScheduleCsvFailedError()
        return dataframe

    def _update_query_context(self) -> None:
        """
        Update chart query context.

        To load CSV data from the endpoint the chart must have been saved
        with its query context. For charts without saved query context we
        get a screenshot to force the chart to produce and save the query
        context.
        """
        try:
            self._get_screenshots()
        except (
            ReportScheduleScreenshotFailedError,
            ReportScheduleScreenshotTimeout,
        ) as ex:
            raise ReportScheduleCsvFailedError(
                "Unable to fetch data because the chart has no query context "
                "saved, and an error occurred when fetching it via a screenshot. "
                "Please try loading the chart and saving it again."
            ) from ex

    def _get_log_data(self) -> HeaderDataType:
        chart_id = None
        dashboard_id = None
        report_source = None
        slack_channels = None
        if self._report_schedule.chart:
            report_source = ReportSourceFormat.CHART
            chart_id = self._report_schedule.chart_id
        else:
            report_source = ReportSourceFormat.DASHBOARD
            dashboard_id = self._report_schedule.dashboard_id

        if self._report_schedule.recipients:
            slack_channels = [
                recipient.recipient_config_json
                for recipient in self._report_schedule.recipients
                if recipient.type
                in [ReportRecipientType.SLACK, ReportRecipientType.SLACKV2]
            ]

        log_data: HeaderDataType = {
            "notification_type": self._report_schedule.type,
            "notification_source": report_source,
            "notification_format": self._report_schedule.report_format,
            "chart_id": chart_id,
            "dashboard_id": dashboard_id,
            "owners": self._report_schedule.owners,
            "slack_channels": slack_channels,
        }
        return log_data

    def _get_notification_content(self) -> NotificationContent:
        """
        Gets a notification content, this is composed by a title and a screenshot

        :raises: ReportScheduleScreenshotFailedError
        """
        csv_data = None
        screenshot_data = []
        pdf_data = None
        embedded_data = None
        error_text = None
        header_data = self._get_log_data()
        url = self._get_url(user_friendly=True)
        if (
            feature_flag_manager.is_feature_enabled("ALERTS_ATTACH_REPORTS")
            or self._report_schedule.type == ReportScheduleType.REPORT
        ):
            if self._report_schedule.report_format == ReportDataFormat.PNG:
                screenshot_data = self._get_screenshots()
                if not screenshot_data:
                    error_text = "Unexpected missing screenshot"
            elif self._report_schedule.report_format == ReportDataFormat.PDF:
                pdf_data = self._get_pdf()
                if not pdf_data:
                    error_text = "Unexpected missing pdf"
            elif (
                self._report_schedule.chart
                and self._report_schedule.report_format == ReportDataFormat.CSV
            ):
                csv_data = self._get_csv_data()
                if not csv_data:
                    error_text = "Unexpected missing csv file"
            if error_text:
                return NotificationContent(
                    name=self._report_schedule.name,
                    text=error_text,
                    header_data=header_data,
                    url=url,
                )

        if (
            self._report_schedule.chart
            and self._report_schedule.report_format == ReportDataFormat.TEXT
        ):
            embedded_data = self._get_embedded_data()

        if self._report_schedule.email_subject:
            name = self._report_schedule.email_subject
        else:
            if self._report_schedule.chart:
                name = (
                    f"{self._report_schedule.name}: "
                    f"{self._report_schedule.chart.slice_name}"
                )
            else:
                name = (
                    f"{self._report_schedule.name}: "
                    f"{self._report_schedule.dashboard.dashboard_title}"
                )

        return NotificationContent(
            name=name,
            url=url,
            screenshots=screenshot_data,
            pdf=pdf_data,
            description=self._report_schedule.description,
            csv=csv_data,
            embedded_data=embedded_data,
            header_data=header_data,
            report_schedule=self._report_schedule,
        )

    def _send(
        self,
        notification_content: NotificationContent,
        recipients: list[ReportRecipients],
    ) -> None:
        """
        Sends a notification to all recipients

        :raises: CommandException
        """
        notification_errors: list[SupersetError] = []
        for recipient in recipients:
            notification = create_notification(recipient, notification_content)
            try:
                if app.config["ALERT_REPORTS_NOTIFICATION_DRY_RUN"]:
                    logger.info(
                        "Would send notification for alert %s, to %s. "
                        "ALERT_REPORTS_NOTIFICATION_DRY_RUN is enabled, "
                        "set it to False to send notifications.",
                        self._report_schedule.name,
                        recipient.recipient_config_json,
                    )
                else:
                    notification.send()
            except SlackV1NotificationError as ex:
                # The slack notification should be sent with the v2 api
                logger.info("Attempting to upgrade the report to Slackv2: %s", str(ex))
                try:
                    self.update_report_schedule_slack_v2()
                    recipient.type = ReportRecipientType.SLACKV2
                    notification = create_notification(recipient, notification_content)
                    notification.send()
                except (UpdateFailedError, NotificationParamException) as err:
                    # log the error but keep processing the report with SlackV1
                    logger.warning(
                        "Failed to update slack recipients to v2: %s", str(err)
                    )
            except (NotificationError, SupersetException) as ex:
                # collect errors but keep processing them
                notification_errors.append(
                    SupersetError(
                        message=ex.message,
                        error_type=SupersetErrorType.REPORT_NOTIFICATION_ERROR,
                        level=ErrorLevel.ERROR
                        if ex.status >= 500
                        else ErrorLevel.WARNING,
                    )
                )
        if notification_errors:
            # log all errors but raise based on the most severe
            for error in notification_errors:
                logger.warning(str(error))

            if any(error.level == ErrorLevel.ERROR for error in notification_errors):
                raise ReportScheduleSystemErrorsException(errors=notification_errors)
            if any(error.level == ErrorLevel.WARNING for error in notification_errors):
                raise ReportScheduleClientErrorsException(errors=notification_errors)

    def send(self) -> None:
        """
        Creates the notification content and sends them to all recipients

        :raises: CommandException
        """
        notification_content = self._get_notification_content()
        self._send(notification_content, self._report_schedule.recipients)

    def send_error(self, name: str, message: str) -> None:
        """
        Creates and sends a notification for an error, to all recipients

        :raises: CommandException
        """
        header_data = self._get_log_data()
        url = self._get_url(user_friendly=True)
        logger.info(
            "header_data in notifications for alerts and reports %s, taskid, %s",
            header_data,
            self._execution_id,
        )
        notification_content = NotificationContent(
            name=name, text=message, header_data=header_data, url=url
        )

        # filter recipients to recipients who are also owners
        owner_recipients = [
            ReportRecipients(
                type=ReportRecipientType.EMAIL,
                recipient_config_json=json.dumps({"target": owner.email}),
            )
            for owner in self._report_schedule.owners
        ]

        self._send(notification_content, owner_recipients)

    def is_in_grace_period(self) -> bool:
        """
        Checks if an alert is in it's grace period
        """
        last_success = ReportScheduleDAO.find_last_success_log(self._report_schedule)
        return (
            last_success is not None
            and self._report_schedule.grace_period
            and datetime.utcnow()
            - timedelta(seconds=self._report_schedule.grace_period)
            < last_success.end_dttm
        )

    def is_in_error_grace_period(self) -> bool:
        """
        Checks if an alert/report on error is in it's notification grace period
        """
        last_success = ReportScheduleDAO.find_last_error_notification(
            self._report_schedule
        )
        if not last_success:
            return False
        return (
            last_success is not None
            and self._report_schedule.grace_period
            and datetime.utcnow()
            - timedelta(seconds=self._report_schedule.grace_period)
            < last_success.end_dttm
        )

    def is_on_working_timeout(self) -> bool:
        """
        Checks if an alert is in a working timeout
        """
        last_working = ReportScheduleDAO.find_last_entered_working_log(
            self._report_schedule
        )
        if not last_working:
            return False
        return (
            self._report_schedule.working_timeout is not None
            and self._report_schedule.last_eval_dttm is not None
            and datetime.utcnow()
            - timedelta(seconds=self._report_schedule.working_timeout)
            > last_working.end_dttm
        )

    def next(self) -> None:
        raise NotImplementedError()


class ReportNotTriggeredErrorState(BaseReportState):
    """
    Handle Not triggered and Error state
    next final states:
    - Not Triggered
    - Success
    - Error
    """

    current_states = [ReportState.NOOP, ReportState.ERROR]
    initial = True

    def next(self) -> None:
        self.update_report_schedule_and_log(ReportState.WORKING)
        try:
            # If it's an alert check if the alert is triggered
            if self._report_schedule.type == ReportScheduleType.ALERT:
                if not AlertCommand(self._report_schedule).run():
                    self.update_report_schedule_and_log(ReportState.NOOP)
                    return
            self.send()
            self.update_report_schedule_and_log(ReportState.SUCCESS)
        except (SupersetErrorsException, Exception) as first_ex:
            error_message = str(first_ex)
            if isinstance(first_ex, SupersetErrorsException):
                error_message = ";".join([error.message for error in first_ex.errors])

            self.update_report_schedule_and_log(
                ReportState.ERROR, error_message=error_message
            )

            # TODO (dpgaspar) convert this logic to a new state eg: ERROR_ON_GRACE
            if not self.is_in_error_grace_period():
                second_error_message = REPORT_SCHEDULE_ERROR_NOTIFICATION_MARKER
                try:
                    self.send_error(
                        f"Error occurred for {self._report_schedule.type}:"
                        f" {self._report_schedule.name}",
                        str(first_ex),
                    )

                except SupersetErrorsException as second_ex:
                    second_error_message = ";".join(
                        [error.message for error in second_ex.errors]
                    )
                except Exception as second_ex:  # pylint: disable=broad-except
                    second_error_message = str(second_ex)
                finally:
                    self.update_report_schedule_and_log(
                        ReportState.ERROR, error_message=second_error_message
                    )
            raise


class ReportWorkingState(BaseReportState):
    """
    Handle Working state
    next states:
    - Error
    - Working
    """

    current_states = [ReportState.WORKING]

    def next(self) -> None:
        if self.is_on_working_timeout():
            exception_timeout = ReportScheduleWorkingTimeoutError()
            self.update_report_schedule_and_log(
                ReportState.ERROR,
                error_message=str(exception_timeout),
            )
            raise exception_timeout
        exception_working = ReportSchedulePreviousWorkingError()
        self.update_report_schedule_and_log(
            ReportState.WORKING,
            error_message=str(exception_working),
        )
        raise exception_working


class ReportSuccessState(BaseReportState):
    """
    Handle Success, Grace state
    next states:
    - Grace
    - Not triggered
    - Success
    """

    current_states = [ReportState.SUCCESS, ReportState.GRACE]

    def next(self) -> None:
        if self._report_schedule.type == ReportScheduleType.ALERT:
            if self.is_in_grace_period():
                self.update_report_schedule_and_log(
                    ReportState.GRACE,
                    error_message=str(ReportScheduleAlertGracePeriodError()),
                )
                return
            self.update_report_schedule_and_log(ReportState.WORKING)
            try:
                if not AlertCommand(self._report_schedule).run():
                    self.update_report_schedule_and_log(ReportState.NOOP)
                    return
            except Exception as ex:
                self.send_error(
                    f"Error occurred for {self._report_schedule.type}:"
                    f" {self._report_schedule.name}",
                    str(ex),
                )
                self.update_report_schedule_and_log(
                    ReportState.ERROR,
                    error_message=REPORT_SCHEDULE_ERROR_NOTIFICATION_MARKER,
                )
                raise

        try:
            self.send()
            self.update_report_schedule_and_log(ReportState.SUCCESS)
        except Exception as ex:  # pylint: disable=broad-except
            self.update_report_schedule_and_log(
                ReportState.ERROR, error_message=str(ex)
            )


class ReportScheduleStateMachine:  # pylint: disable=too-few-public-methods
    """
    Simple state machine for Alerts/Reports states
    """

    states_cls = [ReportWorkingState, ReportNotTriggeredErrorState, ReportSuccessState]

    def __init__(
        self,
        task_uuid: UUID,
        report_schedule: ReportSchedule,
        scheduled_dttm: datetime,
        as_of_date: Optional[str] = None,
        filter_date: Optional[str] = None,
    ):
        self._execution_id = task_uuid
        self._report_schedule = report_schedule
        self._scheduled_dttm = scheduled_dttm
        self._as_of_date = as_of_date
        self._filter_date = filter_date

    @transaction()
    def run(self) -> None:
        for state_cls in self.states_cls:
            if (self._report_schedule.last_state is None and state_cls.initial) or (
                self._report_schedule.last_state in state_cls.current_states
            ):
                state_cls(
                    self._report_schedule,
                    self._scheduled_dttm,
                    self._execution_id,
                    as_of_date=self._as_of_date,
                    filter_date=self._filter_date,
                ).next()
                break
        else:
            raise ReportScheduleStateNotFoundError()


class AsyncExecuteReportScheduleCommand(BaseCommand):
    """
    Execute all types of report schedules.
    - On reports takes chart or dashboard screenshots and sends configured notifications
    - On Alerts uses related Command AlertCommand and sends configured notifications
    """

    def __init__(
        self,
        task_id: str,
        model_id: int,
        scheduled_dttm: datetime,
        as_of_date: Optional[str] = None,
        filter_date: Optional[str] = None,
    ):
        self._model_id = model_id
        self._model: Optional[ReportSchedule] = None
        self._scheduled_dttm = scheduled_dttm
        self._execution_id = UUID(task_id)
        self._as_of_date = as_of_date
        self._filter_date = filter_date

    @transaction()
    def run(self) -> None:
        try:
            self.validate()
            if not self._model:
                raise ReportScheduleExecuteUnexpectedError()
            _, username = get_executor(
                executor_types=app.config["ALERT_REPORTS_EXECUTE_AS"],
                model=self._model,
            )
            user = security_manager.find_user(username)
            with override_user(user):
                logger.info(
                    "Running report schedule %s as user %s",
                    self._execution_id,
                    username,
                )
                ReportScheduleStateMachine(
                    self._execution_id,
                    self._model,
                    self._scheduled_dttm,
                    as_of_date=self._as_of_date,
                    filter_date=self._filter_date,
                ).run()
        except CommandException:
            raise
        except Exception as ex:
            raise ReportScheduleUnexpectedError(str(ex)) from ex

    def validate(self) -> None:
        # Validate/populate model exists
        logger.info(
            "session is validated: id %s, executionid: %s",
            self._model_id,
            self._execution_id,
        )
        self._model = (
            db.session.query(ReportSchedule).filter_by(id=self._model_id).one_or_none()
        )
        if not self._model:
            raise ReportScheduleNotFoundError()
