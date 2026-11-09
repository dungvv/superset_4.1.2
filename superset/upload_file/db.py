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
"""Queries and writes on a database connection defined in Superset (the DWH)."""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Optional

from sqlalchemy import bindparam, text

logger = logging.getLogger(__name__)

# Name of the database connection in Superset (Settings > Database Connections)
# that holds the source tables and the Upload file history tables.
DWH_CONNECTION = "DWH_APP Oracle"
# Schema owning the UPLOAD_FILE_* tables; None = the schema of the connection user
DWH_SCHEMA: Optional[str] = None

# Oracle accepts at most 1000 items in an IN list
IN_CHUNK_SIZE = 500


def chunks(values: Sequence[str], size: int = IN_CHUNK_SIZE) -> Iterator[list[str]]:
    for i in range(0, len(values), size):
        yield list(values[i : i + size])


@contextmanager
def dwh_connection(
    database_name: str = DWH_CONNECTION, write: bool = False
) -> Iterator[Any]:
    """A SQLAlchemy connection on the DWH.

    With ``write`` everything done inside the ``with`` block is one
    transaction: committed when it ends, rolled back on an error.
    """
    # Imported here: this module is loaded early, superset.models needs the app
    from superset import db
    from superset.models.core import Database

    database = (
        db.session.query(Database).filter_by(database_name=database_name).one_or_none()
    )
    if database is None:
        raise LookupError(f"Database connection {database_name!r} not found")
    with database.get_sqla_engine() as engine:
        if write:
            with engine.begin() as connection:
                yield connection
        else:
            with engine.connect() as connection:
                yield connection


def query_in_chunks(
    database_name: str,
    sql: str,
    ids: Sequence[str],
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run ``sql`` for every chunk of ``ids`` and return the rows as dicts.

    ``sql`` must contain an ``IN :ids`` clause. Every value is sent as a bound
    parameter, nothing is concatenated into the statement. Column names are
    upper-cased.
    """
    statement = text(sql).bindparams(bindparam("ids", expanding=True))
    rows: list[dict[str, Any]] = []
    with dwh_connection(database_name) as connection:
        for chunk in chunks(list(ids)):
            result = connection.execute(statement, {**params, "ids": chunk})
            keys = [str(k).upper() for k in result.keys()]
            rows.extend(dict(zip(keys, row)) for row in result.fetchall())
    return rows
