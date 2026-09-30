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
"""Role form: assign dashboards (DASHBOARD_RBAC) from /roles/add|edit."""

from __future__ import annotations

import logging
from typing import Any, Optional

from flask import abort, flash, request
from flask_appbuilder.fieldwidgets import Select2ManyWidget
from flask_appbuilder.security.views import RoleModelView
from flask_appbuilder.urltools import (
    get_filter_args,
    get_order_args,
    get_page_args,
    get_page_size_args,
)
from flask_babel import lazy_gettext
from wtforms import SelectMultipleField

from superset.security.list_search import KEYWORD_LIST_TEMPLATE, KeywordSearchFilter

logger = logging.getLogger(__name__)


class NonModelSelectMultipleField(SelectMultipleField):
    """SelectMultipleField that is not written onto the SQLAlchemy model."""

    def populate_obj(self, obj: Any, name: str) -> None:  # noqa: ARG002
        return


def _dashboard_choices() -> list[tuple[int, str]]:
    # Lazy import: avoid circular import (extensions → manager → this module)
    from superset.extensions import db
    from superset.models.dashboard import Dashboard

    rows = (
        db.session.query(Dashboard.id, Dashboard.dashboard_title)
        .order_by(Dashboard.dashboard_title.asc())
        .all()
    )
    return [
        (row.id, row.dashboard_title or f"Dashboard #{row.id}") for row in rows
    ]


def _dashboard_ids_for_role(role_id: int) -> list[int]:
    from superset.extensions import db
    from superset.models.dashboard import Dashboard

    rows = (
        db.session.query(Dashboard.id)
        .filter(Dashboard.roles.any(id=role_id))
        .order_by(Dashboard.dashboard_title.asc())
        .all()
    )
    return [row.id for row in rows]


def sync_role_dashboards(role: Any, dashboard_ids: Optional[list[int]]) -> None:
    """
    Sync dashboard_roles for ``role`` to exactly ``dashboard_ids``.

    Only adds/removes this role on each dashboard; other roles are kept.
    """
    from flask_appbuilder.security.sqla.models import Role
    from superset.extensions import db
    from superset.models.dashboard import Dashboard

    if role is None or not getattr(role, "id", None):
        return

    role_obj = db.session.query(Role).filter_by(id=role.id).one_or_none()
    if role_obj is None:
        return

    selected = {int(i) for i in (dashboard_ids or []) if i is not None}

    current_dashboards = (
        db.session.query(Dashboard)
        .filter(Dashboard.roles.any(id=role_obj.id))
        .all()
    )
    current_ids = {d.id for d in current_dashboards}

    to_add = selected - current_ids
    to_remove = current_ids - selected

    if to_add:
        for dash in (
            db.session.query(Dashboard).filter(Dashboard.id.in_(to_add)).all()
        ):
            if role_obj not in dash.roles:
                dash.roles.append(role_obj)

    if to_remove:
        for dash in current_dashboards:
            if dash.id in to_remove and role_obj in dash.roles:
                dash.roles.remove(role_obj)

    db.session.commit()
    logger.info(
        "Synced dashboards for role_id=%s selected=%s added=%s removed=%s",
        role_obj.id,
        sorted(selected),
        sorted(to_add),
        sorted(to_remove),
    )


def _make_dashboard_field() -> NonModelSelectMultipleField:
    return NonModelSelectMultipleField(
        lazy_gettext("Dashboards"),
        coerce=int,
        choices=[],
        validators=[],
        widget=Select2ManyWidget(),
        description=lazy_gettext(
            "Select dashboards this role can access (DASHBOARD_RBAC). "
            "Same effect as assigning the role under each dashboard's Properties."
        ),
    )


def _parse_dashboard_ids(raw: Any) -> list[int]:
    if not raw:
        return []
    result: list[int] = []
    for item in raw:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


class UnitelRoleModelView(RoleModelView):
    """FAB Role CRUD with an extra Dashboards multi-select."""

    # Keep the same FAB permission name as stock RoleModelView so existing
    # Admin / role grants (can_list/can_edit/... on RoleModelView) still work.
    class_permission_name = "RoleModelView"

    list_template = KEYWORD_LIST_TEMPLATE
    extra_args = {
        "keyword_label": lazy_gettext("Name"),
        "keyword_placeholder": lazy_gettext("Type a value"),
    }
    base_filters = [["name", KeywordSearchFilter, ("name",)]]

    list_columns = ["name"]
    add_columns = ["name", "permissions", "dashboards"]
    edit_columns = ["name", "permissions", "user", "dashboards"]
    related_views = []

    label_columns = {
        "name": lazy_gettext("Name"),
        "permissions": lazy_gettext("Permissions"),
        "user": lazy_gettext("User"),
        "dashboards": lazy_gettext("Dashboards"),
    }
    description_columns = {
        "dashboards": lazy_gettext(
            "Select dashboards this role can access (DASHBOARD_RBAC). "
            "Same effect as assigning the role under each dashboard's Properties."
        ),
    }

    add_form_extra_fields = {
        "dashboards": _make_dashboard_field(),
    }
    edit_form_extra_fields = {
        "dashboards": _make_dashboard_field(),
    }

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pending_dashboard_ids: list[int] = []

    def _refresh_dashboard_field(self, form: Any) -> None:
        if hasattr(form, "dashboards"):
            form.dashboards.choices = _dashboard_choices()

    def prefill_form(self, form: Any, pk: Any) -> None:
        self._refresh_dashboard_field(form)
        try:
            role_id = int(pk)
        except (TypeError, ValueError):
            return
        form.dashboards.data = _dashboard_ids_for_role(role_id)

    def process_form(self, form: Any, is_created: bool) -> None:  # noqa: ARG002
        raw = form.dashboards.data if hasattr(form, "dashboards") else None
        if raw is None and request.method == "POST":
            raw = request.form.getlist("dashboards")
        self._pending_dashboard_ids = _parse_dashboard_ids(raw)

    def post_add(self, item: Any) -> None:
        sync_role_dashboards(item, self._pending_dashboard_ids)
        self._pending_dashboard_ids = []

    def post_update(self, item: Any) -> None:
        sync_role_dashboards(item, self._pending_dashboard_ids)
        self._pending_dashboard_ids = []

    def _add(self) -> Any:
        """Same as FAB ModelView._add, but refresh dashboard choices before validate."""
        is_valid_form = True
        get_filter_args(self._filters, disallow_if_not_in_search=False)
        exclude_cols = self._filters.get_relation_cols()
        form = self.add_form.refresh()
        self._refresh_dashboard_field(form)

        if request.method == "POST":
            self._fill_form_exclude_cols(exclude_cols, form)
            if form.validate():
                self.process_form(form, True)
                item = self.datamodel.obj()
                try:
                    form.populate_obj(item)
                    self.pre_add(item)
                except Exception as exc:  # pylint: disable=broad-except
                    flash(str(exc), "danger")
                else:
                    try:
                        self.datamodel.add(item)
                        self.post_add(item)
                        flash(self.add_row_message, "success")
                    except Exception as exc:  # pylint: disable=broad-except
                        flash(str(exc), "danger")
                    finally:
                        return None
            else:
                is_valid_form = False
        if is_valid_form:
            self.update_redirect()
        return self._get_add_widget(form=form, exclude_cols=exclude_cols)

    def _edit(self, pk: Any) -> Any:
        """Same as FAB ModelView._edit, but refresh dashboard choices before validate."""
        is_valid_form = True
        pages = get_page_args()
        page_sizes = get_page_size_args()
        orders = get_order_args()
        get_filter_args(self._filters, disallow_if_not_in_search=False)
        exclude_cols = self._filters.get_relation_cols()

        item = self.datamodel.get(pk, self._base_filters)
        if not item:
            abort(404)
        pk = self.datamodel.get_pk_value(item)

        if request.method == "POST":
            form = self.edit_form.refresh(request.form)
            self._refresh_dashboard_field(form)
            self._fill_form_exclude_cols(exclude_cols, form)
            form._id = pk  # noqa: SLF001
            if form.validate():
                self.process_form(form, False)
                try:
                    form.populate_obj(item)
                    self.pre_update(item)
                except Exception as exc:  # pylint: disable=broad-except
                    flash(str(exc), "danger")
                else:
                    try:
                        self.datamodel.edit(item)
                        self.post_update(item)
                        flash(self.edit_row_message, "success")
                    except Exception:  # pylint: disable=broad-except
                        flash(self.database_error_message, "danger")
                    finally:
                        return None
            else:
                is_valid_form = False
        else:
            form = self.edit_form.refresh(obj=item)
            self.prefill_form(form, pk)

        widgets = self._get_edit_widget(form=form, exclude_cols=exclude_cols)
        widgets = self._get_related_views_widgets(
            item,
            filters={},
            orders=orders,
            pages=pages,
            page_sizes=page_sizes,
            widgets=widgets,
        )
        if is_valid_form:
            self.update_redirect()
        return widgets
