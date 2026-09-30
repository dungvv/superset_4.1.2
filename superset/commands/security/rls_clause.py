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
"""Reject RLS rules whose clause references columns missing from a dataset."""

from __future__ import annotations

import logging
from typing import Optional

import sqlglot
from flask_babel import gettext as _
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from superset.commands.security.exceptions import RLSClauseValidationError
from superset.connectors.sqla.models import SqlaTable
from superset.sql.parse import SQLGLOT_DIALECTS

logger = logging.getLogger(__name__)

# Identifiers that parse as columns but are keywords / pseudo-columns.
PSEUDO_COLUMNS = {
    "current_date",
    "current_time",
    "current_timestamp",
    "current_user",
    "false",
    "level",
    "localtimestamp",
    "null",
    "rowid",
    "rownum",
    "session_user",
    "sysdate",
    "systimestamp",
    "true",
    "uid",
    "user",
}


def _render_clause(clause: str, table: SqlaTable) -> str:
    try:
        return table.get_template_processor().process_template(clause)
    except Exception as ex:  # pylint: disable=broad-except
        raise RLSClauseValidationError(
            _("Error in jinja expression in clause: %(error)s", error=str(ex))
        ) from ex


def _referenced_columns(clause: str, dialect: Optional[str]) -> set[str]:
    try:
        tree = sqlglot.parse_one(f"SELECT 1 FROM t WHERE {clause}", dialect=dialect)
    except (ParseError, TokenError) as ex:
        raise RLSClauseValidationError(
            _("Could not parse clause: %(error)s", error=str(ex))
        ) from ex

    where = tree.args.get("where")
    if where is None:
        raise RLSClauseValidationError(_("Could not parse clause."))

    names: set[str] = set()
    for column in where.find_all(exp.Column):
        # Columns inside a subquery belong to the subquery's own tables.
        node = column.parent
        in_subquery = False
        while node is not None and node is not where:
            if isinstance(node, exp.Select):
                in_subquery = True
                break
            node = node.parent
        if in_subquery:
            continue
        if column.name and column.name.lower() not in PSEUDO_COLUMNS:
            names.add(column.name)
    return names


def validate_clause_columns(clause: Optional[str], tables: list[SqlaTable]) -> None:
    """
    Raise RLSClauseValidationError if ``clause`` references a column that is not
    a physical column of every dataset in ``tables``.

    Calculated columns are excluded: the clause is injected as raw SQL into the
    WHERE of the dataset query, where only real columns exist.
    """
    if not clause or not tables:
        return

    missing_by_table: list[str] = []
    for table in tables:
        dialect = SQLGLOT_DIALECTS.get(table.database.db_engine_spec.engine)
        referenced = _referenced_columns(_render_clause(clause, table), dialect)
        available = {
            col.column_name.lower() for col in table.columns if not col.expression
        }
        missing = sorted(
            name for name in referenced if name.lower() not in available
        )
        if missing:
            missing_by_table.append(f"{table.name} ({', '.join(missing)})")

    if missing_by_table:
        raise RLSClauseValidationError(
            _(
                "Clause references columns that do not exist in these datasets: "
                "%(details)s. Check the column names, or sync the dataset "
                "columns from source if the column was added recently.",
                details="; ".join(missing_by_table),
            )
        )
