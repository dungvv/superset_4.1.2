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
"""Base class of the per business type handlers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from superset.upload_file.validator import (
    read_rows,
    ValidationResult,
    validate_template,
)


class ProcessError(Exception):
    """The file is valid but could not be processed (query failed, ...)."""


@dataclass
class ProcessResult:
    columns: list[str]
    # Source of each column, used to colour the output ("input", "core", ...)
    groups: list[str]
    rows: list[list[str]]
    summary: dict[str, int] = field(default_factory=dict)
    # One dict per row, keyed by the column of the service's detail table, with
    # typed values: they are what is saved in the DWH (see history.py)
    records: list[dict[str, Any]] = field(default_factory=list, repr=False)


class BusinessHandler(ABC):
    """Handles the files uploaded for one business type.

    To add a business type, subclass this, set ``value``, ``label`` and
    ``columns`` and register the class in ``handlers/__init__.py``. Override
    ``validate_data`` for rules on the content, and ``process`` once the
    processing of the type is defined.
    """

    value: str
    label: str
    # Exact column names of the template (order and letter case are free in
    # the uploaded file)
    columns: tuple[str, ...]
    # Output columns (names and sources, in order) and the SQLAlchemy table of the
    # DWH where the rows of the output are saved (one table per service)
    output_columns: list[str]
    output_groups: list[str]
    detail_table: Any
    # Downloadable template: description of each column, sample rows and the
    # columns holding numbers (every other column is formatted as text)
    template_descriptions: dict[str, str]
    template_sample_rows: list[list[str]]
    template_number_columns: frozenset[str] = frozenset()

    def validate(self, filename: str, content: bytes) -> ValidationResult:
        """Return whether the uploaded file follows this type's template."""
        result = validate_template(
            self.label, self.columns, read_rows(filename, content)
        )
        if result.valid:
            # Rows are edited in place: the preview shares them
            errors = self.normalize_rows(result.rows) or self.validate_data(result.rows)
            if errors:
                result.valid = False
                result.errors = errors
        return result

    def normalize_rows(  # pylint: disable=unused-argument
        self, rows: list[list[str]]
    ) -> list[str]:
        """Put the values of the rows in their standard form (in place).

        Returns the errors that refuse the file, if any.
        """
        return []

    def validate_data(self, rows: list[list[str]]) -> list[str]:  # pylint: disable=unused-argument
        """Type specific checks on the content. Returns a list of errors."""
        return []

    @abstractmethod
    def process(self, validation: ValidationResult) -> ProcessResult:
        """Process a valid file (rows are in template column order)."""

    @abstractmethod
    def result_from_records(self, records: list[dict[str, Any]]) -> ProcessResult:
        """Rebuild the output from the rows saved in ``detail_table``."""
