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
import calendar
import logging
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any, Iterator, Optional, Union
from uuid import UUID

import pandas as pd
from celery.exceptions import SoftTimeLimitExceeded
from flask import g

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


def _filter_keeps_for_send_now(flt: dict[str, Any], col: Optional[str]) -> bool:
    """Keep non-temporal filters that are unrelated to the send-now date column."""
    subject = str(flt.get("col") or flt.get("subject") or "").casefold()
    op = flt.get("op") or flt.get("operator")
    if col and subject == col.casefold():
        return False
    if op == FilterOperator.TEMPORAL_RANGE.value:
        return False
    sql_expr = flt.get("sqlExpression") or ""
    if _is_relative_sql_clause(sql_expr):
        return False
    if col and col.casefold() in sql_expr.casefold():
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


def _sanitize_saved_dashboard_filters(
    form_data: dict[str, Any], col: Optional[str]
) -> None:
    """
    Drop date constraints that a chart inherited from dashboard native filters.

    Charts edited from a dashboard are saved with the dashboard's filter state
    in ``extra_form_data`` (e.g. report_date IN (...), time_range "Last day",
    TRUNC(SYSDATE) SQL). The frontend merges it into every query, so together
    with the Send now date it returns No data. Keep the non-date parts.
    """
    extra = form_data.get("extra_form_data")
    if isinstance(extra, dict):
        extra = dict(extra)
        for key in (
            "time_range",
            "granularity_sqla",
            "relative_start",
            "relative_end",
        ):
            extra.pop(key, None)
        extra["filters"] = [
            flt
            for flt in extra.get("filters") or []
            if isinstance(flt, dict) and _filter_keeps_for_send_now(flt, col)
        ]
        extra["adhoc_filters"] = [
            flt
            for flt in extra.get("adhoc_filters") or []
            if isinstance(flt, dict)
            and _filter_keeps_for_send_now(
                {
                    "subject": flt.get("subject"),
                    "operator": flt.get("operator"),
                    "sqlExpression": flt.get("sqlExpression"),
                },
                col,
            )
        ]
        for key in ("filters", "adhoc_filters"):
            if not extra[key]:
                extra.pop(key)
        form_data["extra_form_data"] = extra

    if isinstance(form_data.get("extra_filters"), list):
        form_data["extra_filters"] = [
            flt
            for flt in form_data["extra_filters"]
            if isinstance(flt, dict) and _filter_keeps_for_send_now(flt, col)
        ]


def _shift_month(day: date, months: int) -> date:
    """Same day ``months`` away, clamped to month end (as the time filter does)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def build_send_now_template_params(as_of_date: str) -> dict[str, str]:
    """
    Date parameters the dashboard time filter (plugin-chart-time-filter) puts in
    the URL for grain "day": month-to-date up to the day, compared with the same
    span of the previous month. Datasets read them via url_param() / extras.
    """
    day = datetime.strptime(as_of_date[:10], "%Y-%m-%d").date()
    cur_start = day.replace(day=1)
    cmp_end = _shift_month(day, -1)
    cmp_start = cmp_end.replace(day=1)

    def time_range(start: date, end: date) -> str:
        return f"{start.isoformat()} : {(end + timedelta(days=1)).isoformat()}"

    return {
        "time_grain": "day",
        "grain_value": day.isoformat(),
        "time_range": "|".join(
            [
                cur_start.isoformat(),
                day.isoformat(),
                cmp_start.isoformat(),
                cmp_end.isoformat(),
                "day",
            ]
        ),
        "current_time_range": time_range(cur_start, day),
        "comparison_time_range": time_range(cmp_start, cmp_end),
        "current_start_date": cur_start.isoformat(),
        "current_end_date": day.isoformat(),
        "comparison_start_date": cmp_start.isoformat(),
        "comparison_end_date": cmp_end.isoformat(),
        "time_group": "day",
    }


# Template params that also travel as query extras (EXTRA_FORM_DATA override keys)
_SEND_NOW_EXTRA_KEYS = (
    "current_start_date",
    "current_end_date",
    "comparison_start_date",
    "comparison_end_date",
    "comparison_time_range",
    "time_group",
)


def _send_now_extras(params: dict[str, str]) -> dict[str, str]:
    extras = {key: params[key] for key in _SEND_NOW_EXTRA_KEYS}
    extras["time_range_params"] = params["time_range"]
    return extras


def apply_send_now_template_params(
    form_data: dict[str, Any], params: dict[str, str]
) -> None:
    """Set url_params / extra_form_data date params on a chart's form_data."""
    url_params = form_data.get("url_params")
    form_data["url_params"] = {
        **(url_params if isinstance(url_params, dict) else {}),
        **params,
    }
    extra = form_data.get("extra_form_data")
    form_data["extra_form_data"] = {
        **(extra if isinstance(extra, dict) else {}),
        **_send_now_extras(params),
    }


def apply_send_now_template_params_to_query_context(
    query_context: dict[str, Any], params: dict[str, str]
) -> None:
    """Same as apply_send_now_template_params, for a saved query_context."""
    for query in query_context.get("queries") or []:
        url_params = query.get("url_params")
        query["url_params"] = {
            **(url_params if isinstance(url_params, dict) else {}),
            **params,
        }
        extras = query.get("extras")
        query["extras"] = {
            **(extras if isinstance(extras, dict) else {}),
            **_send_now_extras(params),
        }
    form_data = query_context.get("form_data")
    if isinstance(form_data, dict):
        apply_send_now_template_params(form_data, params)


def _chart_uses_date_template(chart: Any) -> bool:
    """
    True when the chart's dataset SQL takes its dates from the time filter
    params (url_param('current_start_date'), {{ current_end_date }}, ...).
    Such charts are driven by those params only: an extra one-day filter on
    filter_date would cut month-to-date / total rows and return No data.
    """
    try:
        sql = getattr(chart.datasource, "sql", None) or ""
    except Exception:  # pylint: disable=broad-except
        return False
    return any(
        marker in sql
        for marker in (
            "current_start_date",
            "current_end_date",
            "comparison_start_date",
            "time_range_params",
        )
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
    _sanitize_saved_dashboard_filters(form_data, col)
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


def _chart_has_column(chart: Any, col: str) -> bool:
    """True when the chart's datasource exposes a column named ``col``."""
    try:
        columns = getattr(chart.datasource, "columns", None) or []
    except Exception:  # pylint: disable=broad-except
        return False
    target = col.casefold()
    return any(
        (getattr(column, "column_name", None) or "").casefold() == target
        for column in columns
    )


def _chart_default_dttm_column(chart: Any) -> Optional[str]:
    """The dataset's "Default datetime" column, when it is a temporal column."""
    try:
        datasource = chart.datasource
        name = getattr(datasource, "main_dttm_col", None)
        columns = getattr(datasource, "columns", None) or []
    except Exception:  # pylint: disable=broad-except
        return None
    if not name:
        return None
    for column in columns:
        if (getattr(column, "column_name", None) or "") == name and getattr(
            column, "is_dttm", False
        ):
            return name
    return None


def _native_filters_on_column(
    metadata: dict[str, Any], cols: set[str]
) -> list[dict[str, Any]]:
    """Non-time native filters whose target column is a send-now date column."""
    cols = {col.casefold() for col in cols}
    matched = []
    for native_filter in metadata.get("native_filter_configuration") or []:
        if not isinstance(native_filter, dict) or not native_filter.get("id"):
            continue
        if native_filter.get("filterType") == "filter_time":
            continue
        for target in native_filter.get("targets") or []:
            if not isinstance(target, dict):
                continue
            column = target.get("column")
            if not isinstance(column, dict):
                continue
            name = column.get("name") or column.get("column_name") or ""
            if name.casefold() in cols:
                matched.append(native_filter)
                break
    return matched


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

        # Prefer explicit Celery kwargs; fall back to extra.send_now only for
        # the execution Send now queued (same task id). Scheduled runs have
        # other task ids, so they never pick up an old Send now date.
        send_now = (report_schedule.extra or {}).get("send_now") or {}
        if str(send_now.get("task_id") or "") != str(execution_id):
            send_now = {}
        self._as_of_date = as_of_date or send_now.get("as_of_date")
        self._filter_date = filter_date or send_now.get("filter_date")
        if isinstance(self._as_of_date, str):
            self._as_of_date = self._as_of_date.strip() or None
        if isinstance(self._filter_date, str):
            self._filter_date = self._filter_date.strip() or None

    def _has_send_now_override(self) -> bool:
        # Dashboards resolve the date column per chart, so filter_date is
        # optional there; chart reports still need it.
        if not self._as_of_date:
            return False
        return bool(self._filter_date or self._report_schedule.dashboard)

    def _send_now_date_column(self, chart: Any) -> Optional[str]:
        """
        Date column used for this chart's one-day filter: the typed
        filter_date when the chart's dataset has it, otherwise the dataset's
        "Default datetime" column. None when neither applies.
        """
        if self._filter_date and _chart_has_column(chart, self._filter_date):
            return self._filter_date.strip()
        return _chart_default_dttm_column(chart)

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
        col = self._filter_date
        template_params = build_send_now_template_params(self._as_of_date)
        if chart and not self._send_now_uses_date_filter(chart):
            _sanitize_saved_dashboard_filters(form_data, col)
            apply_send_now_template_params(form_data, template_params)
            return form_data
        time_range = _build_send_now_time_range(self._as_of_date)
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
        _sanitize_saved_dashboard_filters(form_data, col)
        apply_send_now_template_params(form_data, template_params)
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

        use_date_filter = self._send_now_uses_date_filter(chart)
        qc_dict = json.loads(chart.query_context)
        if use_date_filter:
            qc_dict = apply_send_now_to_query_context(
                qc_dict,
                self._as_of_date,
                self._filter_date,
                backend=backend,
            )
        elif isinstance(qc_dict.get("form_data"), dict):
            _sanitize_saved_dashboard_filters(
                qc_dict["form_data"], self._filter_date.strip()
            )
        apply_send_now_template_params_to_query_context(
            qc_dict, build_send_now_template_params(self._as_of_date)
        )
        qc_dict["result_format"] = result_format
        qc_dict["result_type"] = ChartDataResultType.POST_PROCESSED
        qc_dict["force"] = True

        query_context = ChartDataQueryContextSchema().load(qc_dict)
        if use_date_filter:
            enforce_send_now_on_query_context(
                query_context,
                self._as_of_date,
                self._filter_date,
                backend=backend,
            )
        command = ChartDataCommand(query_context)
        command.validate()
        # url_param() reads url_params from g.form_data when there is no
        # request (Celery), so datasets see the Send now dates.
        had_form_data = hasattr(g, "form_data")
        previous_form_data = getattr(g, "form_data", None)
        g.form_data = deepcopy(qc_dict)
        try:
            result = command.run()
        finally:
            if had_form_data:
                g.form_data = previous_form_data
            else:
                g.pop("form_data", None)

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

    def _send_now_uses_date_filter(self, chart: Any) -> bool:
        """
        Whether Send now adds the one-day date filter to this chart.
        Charts whose dataset takes dates from the time filter params get those
        params instead (see _chart_uses_date_template).
        """
        return bool(
            self._send_now_date_column(chart)
        ) and not _chart_uses_date_template(chart)

    def _send_now_patch_chart(self, chart: Any) -> tuple[Optional[str], str]:
        """
        Return Send now versions of (query_context, params) for one chart:
        the as-of date as time filter params (url_params / extras) for every
        chart, plus the one-day filter_date filter where it applies.
        """
        assert self._as_of_date
        col = self._send_now_date_column(chart)
        template_params = build_send_now_template_params(self._as_of_date)
        use_date_filter = self._send_now_uses_date_filter(chart)
        backend = _chart_db_backend(chart)

        query_context: Optional[str] = chart.query_context
        patched_form_data: Optional[dict[str, Any]] = None
        if chart.query_context:
            try:
                qc_dict = json.loads(chart.query_context)
                if isinstance(qc_dict, dict):
                    if use_date_filter:
                        assert col
                        qc_dict = apply_send_now_to_query_context(
                            qc_dict,
                            self._as_of_date,
                            col,
                            backend=backend,
                        )
                        if isinstance(qc_dict.get("form_data"), dict):
                            patched_form_data = qc_dict["form_data"]
                    elif isinstance(qc_dict.get("form_data"), dict):
                        _sanitize_saved_dashboard_filters(qc_dict["form_data"], col)
                    apply_send_now_template_params_to_query_context(
                        qc_dict, template_params
                    )
                    qc_dict["force"] = True
                    query_context = json.dumps(qc_dict)
            except (TypeError, json.JSONDecodeError, ValueError) as ex:
                logger.warning(
                    "Send now: skip query_context patch slice_id=%s: %s",
                    chart.id,
                    ex,
                )

        try:
            params = json.loads(chart.params) if chart.params else {}
        except (TypeError, json.JSONDecodeError):
            params = {}
        if not isinstance(params, dict):
            params = {}

        if use_date_filter and patched_form_data is not None:
            params["adhoc_filters"] = patched_form_data.get("adhoc_filters", [])
            for key in ("time_range", "granularity_sqla"):
                if key in patched_form_data:
                    params[key] = patched_form_data[key]
                else:
                    params.pop(key, None)
            params.pop("relative_start", None)
            params.pop("relative_end", None)
        elif use_date_filter:
            assert col
            try:
                params = apply_send_now_to_chart_params(
                    params,
                    self._as_of_date,
                    col,
                    backend=backend,
                )
            except ValueError as ex:
                logger.warning(
                    "Send now: skip params date filter slice_id=%s: %s",
                    chart.id,
                    ex,
                )
        _sanitize_saved_dashboard_filters(params, col)
        apply_send_now_template_params(params, template_params)
        params["force"] = True

        logger.info(
            "Send now chart patched: slice_id=%s backend=%s date_column=%s "
            "date_filter=%s date_template=%s adhoc_filters=%s url_params=%s",
            chart.id,
            backend,
            col,
            use_date_filter,
            _chart_uses_date_template(chart),
            params.get("adhoc_filters"),
            params.get("url_params"),
        )
        return query_context, json.dumps(params)

    @contextmanager
    def _temporary_chart_query_context(self) -> Iterator[None]:
        """
        Temporarily rewrite chart.query_context/params for Send now.
        Restores the originals afterwards so cron stays unchanged.
        """
        chart = self._report_schedule.chart
        if not chart or not self._has_send_now_override():
            yield
            return

        original_qc = chart.query_context
        original_params = chart.params
        try:
            chart.query_context, chart.params = self._send_now_patch_chart(chart)
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
        Selenium screenshots honor Send now (permalink state alone is not
        enough — charts load their own saved filters and date params).
        Restores originals afterwards so scheduled runs stay unchanged.
        """
        dashboard = self._report_schedule.dashboard
        if not dashboard or not self._has_send_now_override():
            yield
            return

        assert self._as_of_date
        slices = list(dashboard.slices or [])
        date_columns = {
            col for col in map(self._send_now_date_column, slices) if col
        }
        originals: list[tuple[Any, Optional[str], Optional[str]]] = [
            (chart, chart.query_context, chart.params) for chart in slices
        ]
        original_metadata = dashboard.json_metadata
        try:
            # Native filters on the date column are cleared in the permalink
            # dataMask (see _build_send_now_dashboard_state). A "required" filter
            # (enableEmptyFilter) would turn that empty value into 1 = 0 and a
            # defaultToFirstItem filter would pick another date, so relax both.
            try:
                metadata = json.loads(original_metadata or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            date_filters = _native_filters_on_column(metadata, date_columns)
            for native_filter in date_filters:
                control_values = dict(native_filter.get("controlValues") or {})
                control_values["enableEmptyFilter"] = False
                control_values["defaultToFirstItem"] = False
                native_filter["controlValues"] = control_values
            if date_filters:
                dashboard.json_metadata = json.dumps(metadata)

            for chart in slices:
                chart.query_context, chart.params = self._send_now_patch_chart(chart)

            db.session.commit()
            logger.info(
                "Send now dashboard charts patched: report=%s dashboard=%s "
                "as_of=%s filter_date=%s charts=%s",
                self._report_schedule.id,
                dashboard.id,
                self._as_of_date,
                self._filter_date,
                len(slices),
            )
            yield
        finally:
            for chart, original_qc, original_params in originals:
                chart.query_context = original_qc
                chart.params = original_params
            dashboard.json_metadata = original_metadata
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
        assert self._as_of_date
        dashboard = self._report_schedule.dashboard
        day = self._as_of_date[:10]
        time_range = _build_send_now_time_range(day)
        date_columns = {
            col.casefold()
            for col in map(self._send_now_date_column, dashboard.slices or [])
            if col
        }
        col = ", ".join(sorted(date_columns))

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

            # Filters bound to the send-now date column (select/range/...).
            # Their plugins rebuild extraFormData from filterState.value on
            # mount, so a time-range string here becomes
            # "col IN ('YYYY-MM-DD : YYYY-MM-DD')" and every chart shows
            # No data. Clear them; the chart params patch applies the date.
            for target in targets:
                if not isinstance(target, dict):
                    continue
                column = target.get("column") or {}
                if not isinstance(column, dict):
                    continue
                col_name = column.get("name") or column.get("column_name") or ""
                if col_name.casefold() not in date_columns:
                    continue
                data_mask[filter_id] = {
                    "id": filter_id,
                    "extraFormData": {},
                    "filterState": {"value": None},
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
        # Full picture for debugging "No data": every native filter and the
        # dataMask the screenshot browser will start from.
        logger.info(
            "Send now dashboard filters: report=%s native_filters=%s data_mask=%s",
            self._report_schedule.id,
            [
                {
                    "id": nf.get("id"),
                    "type": nf.get("filterType"),
                    "targets": nf.get("targets"),
                    "controlValues": nf.get("controlValues"),
                    "defaultDataMask": nf.get("defaultDataMask"),
                }
                for nf in native_filters
                if isinstance(nf, dict)
            ],
            data_mask,
        )

        # The dashboard time filter (plugin-chart-time-filter) reads its date
        # from these URL params; when any is missing it resets to *today* and
        # reloads, so the screenshot would ignore the Send now date. Datasets
        # also read them via url_param().
        template_params = build_send_now_template_params(day)
        url_params = [
            param
            for param in base_state.get("urlParams") or []
            if param and param[0] not in template_params and param[0] != "force"
        ]
        url_params.extend(template_params.items())
        # Ensure force refresh so screenshot isn't served from stale cache
        url_params.append(("force", "true"))

        return {
            **base_state,
            "dataMask": data_mask,
            "urlParams": url_params,
        }

    def _get_dashboard_tab_paths(self) -> list[list[str]]:
        """
        One image per tab: the tabs picked in the report config
        (extra.dashboard_tabs), or every tab of the dashboard when none is
        picked. Each tab is returned as the activeTabs path needed to open it:
        parent tabs first, the tab last. Nested tabs are captured through their
        innermost tabs, since opening one also renders the content of the tabs
        around it; picking a tab that has nested tabs captures all of them.
        Picked tabs that no longer exist are ignored. An empty list means the
        dashboard has no tabs and is rendered as it opens by default.
        """
        dashboard = self._report_schedule.dashboard
        if not dashboard:
            return []
        try:
            position = json.loads(dashboard.position_json or "{}")
        except (TypeError, json.JSONDecodeError):
            position = {}
        if not isinstance(position, dict):
            return []

        def has_tab_below(node_id: str, seen: set[str]) -> bool:
            node = position.get(node_id)
            if not isinstance(node, dict) or node_id in seen:
                return False
            seen.add(node_id)
            return any(
                (position.get(child) or {}).get("type") == "TAB"
                or has_tab_below(child, seen)
                for child in node.get("children") or []
            )

        paths: list[list[str]] = []

        def walk(node_id: str, tab_path: list[str], seen: set[str]) -> None:
            node = position.get(node_id)
            if not isinstance(node, dict) or node_id in seen:
                return
            seen = seen | {node_id}
            if node.get("type") == "TAB":
                tab_path = [*tab_path, node_id]
                if not has_tab_below(node_id, set()):
                    paths.append(tab_path)
                    return
            for child in node.get("children") or []:
                walk(child, tab_path, seen)

        walk("ROOT_ID", [], set())

        picked = (self._report_schedule.extra or {}).get("dashboard_tabs") or []
        selected = [path for path in paths if set(path) & set(picked)]
        if picked and not selected:
            logger.warning(
                "Report %s: none of the tabs %s exist on dashboard %s, "
                "capturing every tab",
                self._report_schedule.id,
                picked,
                dashboard.id,
            )
        return selected or paths

    def _get_url(
        self,
        user_friendly: bool = False,
        result_format: Optional[ChartDataResultFormat] = None,
        active_tabs: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Get the url for this report schedule: chart or dashboard.
        active_tabs opens the dashboard on those tabs (see _get_dashboard_tab_paths)
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
            if self._has_send_now_override():
                assert self._as_of_date
                # Same date params the dashboard time filter puts in the URL
                kwargs = {
                    **build_send_now_template_params(self._as_of_date),
                    **kwargs,
                }
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
            if active_tabs:
                state["activeTabs"] = active_tabs
            permalink_key = CreateDashboardPermalinkCommand(
                dashboard_id=str(self._report_schedule.dashboard.uuid),
                state=state,
            ).run()
            return get_url_path("Superset.dashboard_permalink", key=permalink_key)

        # Render the dashboard on the tabs picked in the report config
        if active_tabs:
            permalink_key = CreateDashboardPermalinkCommand(
                dashboard_id=str(self._report_schedule.dashboard.uuid),
                state={
                    **(self._report_schedule.extra.get("dashboard") or {}),
                    "activeTabs": active_tabs,
                },
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
                    screenshots: list[Union[ChartScreenshot, DashboardScreenshot]] = [
                        ChartScreenshot(
                            self._get_url(),
                            self._report_schedule.chart.digest,
                            window_size=window_size,
                            thumb_size=app.config["WEBDRIVER_WINDOW"]["slice"],
                        )
                    ]
                else:
                    window_width, window_height = app.config["WEBDRIVER_WINDOW"][
                        "dashboard"
                    ]
                    window_size = (
                        self._report_schedule.custom_width or window_width,
                        self._report_schedule.custom_height or window_height,
                    )
                    # One screenshot per selected tab, or the default view
                    tab_paths: list[Optional[list[str]]] = [
                        *self._get_dashboard_tab_paths()
                    ] or [None]
                    screenshots = [
                        DashboardScreenshot(
                            self._get_url(active_tabs=tab_path),
                            self._report_schedule.dashboard.digest,
                            window_size=window_size,
                            thumb_size=app.config["WEBDRIVER_WINDOW"]["dashboard"],
                        )
                        for tab_path in tab_paths
                    ]

                images: list[bytes] = []
                for screenshot in screenshots:
                    try:
                        image = screenshot.get_screenshot(user=user)
                    except SoftTimeLimitExceeded as ex:
                        logger.warning(
                            "A timeout occurred while taking a screenshot."
                        )
                        raise ReportScheduleScreenshotTimeout() from ex
                    except Exception as ex:
                        raise ReportScheduleScreenshotFailedError(
                            f"Failed taking a screenshot {str(ex)}"
                        ) from ex
                    if not image:
                        raise ReportScheduleScreenshotFailedError()
                    images.append(image)
                return images

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
                try:
                    ReportScheduleStateMachine(
                        self._execution_id,
                        self._model,
                        self._scheduled_dttm,
                        as_of_date=self._as_of_date,
                        filter_date=self._filter_date,
                    ).run()
                finally:
                    self._clear_send_now()
        except CommandException:
            raise
        except Exception as ex:
            raise ReportScheduleUnexpectedError(str(ex)) from ex

    def _clear_send_now(self) -> None:
        """
        Send now is one-shot: once its execution finishes (sent or failed),
        drop extra.send_now and restore force_screenshot so the report's
        schedule runs as configured.
        """
        if not self._model:
            return
        extra = dict(self._model.extra or {})
        send_now = extra.get("send_now") or {}
        if str(send_now.get("task_id") or "") != str(self._execution_id):
            return
        extra.pop("send_now", None)
        self._model.extra = extra
        if "previous_force_screenshot" in send_now:
            self._model.force_screenshot = bool(
                send_now["previous_force_screenshot"]
            )
        try:
            db.session.commit()  # pylint: disable=consider-using-transaction
        except Exception:  # pylint: disable=broad-except
            db.session.rollback()
            logger.warning(
                "Send now: could not clear extra.send_now for report %s",
                self._model_id,
                exc_info=True,
            )

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
