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
"""Utility functions for filename sanitization and processing."""

import re


def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """
    Sanitize a filename by removing invalid filesystem characters.
    
    This function:
    - Removes invalid characters: / \ : * ? " < > |
    - Replaces spaces with the specified replacement character
    - Trims leading/trailing whitespace
    - Collapses multiple consecutive replacement characters into a single one
    
    Args:
        filename: The filename string to sanitize
        replacement: Character to use for replacing invalid chars (default: "_")
    
    Returns:
        Sanitized filename string safe for filesystem use
    
    Examples:
        >>> sanitize_filename("Sales/Performance Report: Q1 2024")
        'Sales_Performance_Report_Q1_2024'
        >>> sanitize_filename("My Report*.xlsx")
        'My_Report_xlsx'
    """
    if not filename:
        return ""
    
    # Trim leading and trailing whitespace
    sanitized = filename.strip()
    
    # Replace spaces with the replacement character
    sanitized = sanitized.replace(" ", replacement)
    
    # Remove invalid filesystem characters: / \ : * ? " < > |
    invalid_chars = r'[/\\:*?"<>|]'
    sanitized = re.sub(invalid_chars, replacement, sanitized)
    
    # Collapse multiple consecutive replacement characters into a single one
    if replacement:
        # Escape the replacement character for regex
        escaped_replacement = re.escape(replacement)
        pattern = f"{escaped_replacement}+"
        sanitized = re.sub(pattern, replacement, sanitized)
    
    # Trim replacement characters from start and end
    sanitized = sanitized.strip(replacement)
    
    return sanitized
