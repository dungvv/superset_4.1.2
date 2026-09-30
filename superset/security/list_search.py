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
"""Keyword search box for the FAB List Users / List Roles pages."""

from __future__ import annotations

from typing import Any

from flask import has_request_context, request
from flask_appbuilder.models.filters import BaseFilter
from flask_appbuilder.security.views import UserDBModelView
from flask_babel import lazy_gettext
from sqlalchemy import or_

KEYWORD_ARG = "q"
KEYWORD_LIST_TEMPLATE = "superset/fab_overrides/keyword_list.html"


def _like_pattern(keyword: str) -> str:
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class KeywordSearchFilter(BaseFilter):
    """
    Case-insensitive "contains" match of ``?q=`` against several columns (OR).

    Used as a base filter; ``value`` is the tuple of column names to search.
    Only applies on the list endpoint so show/edit/delete lookups by pk are
    never narrowed by a leftover ``q`` argument.
    """

    name = "Keyword"
    arg_name = "kw"

    def apply(self, query: Any, value: Any) -> Any:
        if not has_request_context() or not (request.endpoint or "").endswith(
            ".list"
        ):
            return query
        keyword = (request.args.get(KEYWORD_ARG) or "").strip()
        if not keyword:
            return query
        pattern = _like_pattern(keyword)
        return query.filter(
            or_(
                *[
                    getattr(self.model, column).ilike(pattern, escape="\\")
                    for column in value
                ]
            )
        )


class UnitelUserDBModelView(UserDBModelView):
    """FAB List Users with a search box on first name, last name, username."""

    # Keep the stock FAB permission name so existing grants still apply.
    class_permission_name = "UserDBModelView"

    list_template = KEYWORD_LIST_TEMPLATE
    extra_args = {
        "keyword_label": lazy_gettext("Search"),
        "keyword_placeholder": lazy_gettext("First name, last name or username"),
    }
    base_filters = [
        ["username", KeywordSearchFilter, ("first_name", "last_name", "username")]
    ]
