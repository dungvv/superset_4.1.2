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
import time
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote

from flask import g, request, Response
from flask_appbuilder import expose
from flask_appbuilder.security.decorators import has_access, has_access_api
from flask_babel import gettext as __

from superset.superset_typing import FlaskResponse
from superset.upload_file import history
from superset.upload_file.export import build_csv, build_xlsx
from superset.upload_file.handlers.base import ProcessError
from superset.upload_file.handlers import get_handler, list_business_types
from superset.upload_file.validator import UploadFileError
from superset.views.base import BaseSupersetView

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 50


def _content_disposition(filename: str) -> str:
    """Header value that also works for names with accents (RFC 5987)."""
    fallback = filename.encode("ascii", "ignore").decode().replace('"', "") or "result"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


def _parse_day(value: Optional[str]) -> Optional[date]:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


class UploadFileView(BaseSupersetView):
    route_base = "/upload-file"
    class_permission_name = "UploadFile"
    default_view = "page"
    # One permission opens the whole feature (the page and every API): select
    # "can access on UploadFile" in the role's permissions.
    base_permissions = ["can_access"]
    method_permission_name = {
        method: "access"
        for method in (
            "page",
            "business_types",
            "validate",
            "process",
            "history_list",
            "download",
        )
    }

    @expose("/")
    @has_access
    def page(self) -> FlaskResponse:
        return super().render_app_template()

    @expose("/api/business-types", methods=("GET",))
    @has_access_api
    def business_types(self) -> FlaskResponse:
        return self.json_response({"result": list_business_types()})

    def _record(
        self, handler: Any, file_name: str, started: float, **kwargs: Any
    ) -> Optional[int]:
        """Save a check in the DWH history. Never breaks the request."""
        try:
            return history.add_entry(
                handler=handler,
                user_id=getattr(g.user, "id", None),
                username=getattr(g.user, "username", None),
                file_name=file_name,
                duration_ms=int((time.monotonic() - started) * 1000),
                **kwargs,
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception("Unable to save the Upload file history")
            return None

    @expose("/api/validate", methods=("POST",))
    @has_access_api
    def validate(self) -> FlaskResponse:
        """Tell whether an uploaded file follows its business type template.

        A file that is refused is saved in the history (with the reason).
        """
        started = time.monotonic()
        handler = get_handler(request.form.get("business_type"))
        if handler is None:
            return self.json_response({"message": __("Unknown business type")}, 400)

        file = request.files.get("file")
        if not file or not file.filename:
            return self.json_response({"message": __("No file provided")}, 400)

        try:
            result = handler.validate(file.filename, file.read())
        except UploadFileError as ex:
            self._record(handler, file.filename, started, fail_message=str(ex))
            return self.json_response({"message": __(str(ex))}, 400)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to validate uploaded file")
            self._record(handler, file.filename, started, fail_message="Unable to read file")
            return self.json_response({"message": __("Unable to read file")}, 400)

        if not result.valid:
            self._record(handler, file.filename, started, fail_message=". ".join(result.errors))
        return self.json_response(result.to_dict())

    @expose("/api/process", methods=("POST",))
    @has_access_api
    def process(self) -> FlaskResponse:
        """Validate the file, process it and keep the result for download."""
        started = time.monotonic()
        handler = get_handler(request.form.get("business_type"))
        if handler is None:
            return self.json_response({"message": __("Unknown business type")}, 400)

        file = request.files.get("file")
        if not file or not file.filename:
            return self.json_response({"message": __("No file provided")}, 400)

        try:
            validation = handler.validate(file.filename, file.read())
        except UploadFileError as ex:
            self._record(handler, file.filename, started, fail_message=str(ex))
            return self.json_response({"message": __(str(ex))}, 400)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Failed to read uploaded file")
            self._record(handler, file.filename, started, fail_message="Unable to read file")
            return self.json_response({"message": __("Unable to read file")}, 400)
        if not validation.valid:
            self._record(handler, file.filename, started, fail_message=". ".join(validation.errors))
            return self.json_response(validation.to_dict())

        try:
            result = handler.process(validation)
        except ProcessError as ex:
            self._record(handler, file.filename, started, fail_message=str(ex))
            return self.json_response({"message": __(str(ex))}, 502)

        entry_id = self._record(handler, file.filename, started, result=result)
        return self.json_response(
            {
                "valid": True,
                "id": entry_id,
                # False when the DWH could not be written: the result cannot be
                # downloaded later (see the server log)
                "history_saved": entry_id is not None,
                "columns": result.columns,
                "groups": result.groups,
                "total_rows": len(result.rows),
                "summary": result.summary,
                "preview": result.rows[:PREVIEW_ROWS],
            }
        )

    @expose("/api/history", methods=("GET",))
    @has_access_api
    def history_list(self) -> FlaskResponse:
        """The history, 10 per page. Optional filters: service, user (contains),
        file_name (contains), status (success|fail) and a Check Date range (date_from / date_to as
        YYYY-MM-DD, Vietnam days, both included)."""
        try:
            page = int(request.args.get("page", 1))
        except ValueError:
            page = 1
        order_column = request.args.get("order_column", history.DEFAULT_ORDER)
        descending = request.args.get("order_direction", "desc").lower() != "asc"
        try:
            date_from = _parse_day(request.args.get("date_from"))
            date_to = _parse_day(request.args.get("date_to"))
        except ValueError:
            return self.json_response({"message": __("Invalid date")}, 400)
        count, entries = history.list_entries(
            page,
            order_column,
            descending,
            service=(request.args.get("service") or "").strip() or None,
            user=(request.args.get("user") or "").strip() or None,
            file_name=(request.args.get("file_name") or "").strip() or None,
            status=(request.args.get("status") or "").strip().lower() or None,
            date_from=date_from,
            date_to=date_to,
        )
        return self.json_response(
            {"count": count, "page_size": history.PAGE_SIZE, "result": entries}
        )

    @expose("/api/download/<int:entry_id>", methods=("GET",))
    @has_access_api
    def download(self, entry_id: int) -> FlaskResponse:
        file_format = request.args.get("format", "csv").lower()
        if file_format not in {"csv", "xlsx"}:
            return self.json_response({"message": __("Invalid format")}, 400)

        saved = history.get_result(entry_id)
        if saved is None:
            return self.json_response(
                {"message": __("Result expired, please upload again")}, 404
            )

        name, result = saved
        filename = f"{name}.{file_format}"
        if file_format == "csv":
            data, mimetype = build_csv(result), "text/csv"
        else:
            data = build_xlsx(result)
            mimetype = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        return Response(
            data,
            mimetype=mimetype,
            headers={"Content-Disposition": _content_disposition(filename)},
        )
