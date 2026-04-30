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
import textwrap
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import make_msgid, parseaddr
from typing import Any, Optional

import nh3
from flask_babel import gettext as __
from pytz import timezone

from superset import app, is_feature_enabled
from superset.exceptions import SupersetErrorsException
from superset.reports.models import ReportRecipientType
from superset.reports.notifications.base import BaseNotification
from superset.reports.notifications.exceptions import NotificationError
import json
from superset.utils.core import HeaderDataType, send_email_smtp
from superset.utils.decorators import statsd_gauge
from superset.utils.filename_utils import sanitize_filename

logger = logging.getLogger(__name__)

TABLE_TAGS = {"table", "th", "tr", "td", "thead", "tbody", "tfoot"}
TABLE_ATTRIBUTES = {"colspan", "rowspan", "halign", "border", "class"}

ALLOWED_TAGS = {
    "a",
    "abbr",
    "acronym",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "i",
    "li",
    "ol",
    "p",
    "strong",
    "ul",
}.union(TABLE_TAGS)

ALLOWED_TABLE_ATTRIBUTES = {tag: TABLE_ATTRIBUTES for tag in TABLE_TAGS}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "abbr": {"title"},
    "acronym": {"title"},
    **ALLOWED_TABLE_ATTRIBUTES,
}

def _zip_bytes(filename: str, content: bytes) -> bytes:
    """Compress a bytes object into a zip archive containing the file."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(filename, content)
    return zip_buffer.getvalue()

@dataclass
class EmailContent:
    body: str
    header_data: Optional[HeaderDataType] = None
    data: Optional[dict[str, Any]] = None
    pdf: Optional[dict[str, bytes]] = None
    images: Optional[dict[str, bytes]] = None


class EmailNotification(BaseNotification):  # pylint: disable=too-few-public-methods
    """
    Sends an email notification for a report recipient
    """

    type = ReportRecipientType.EMAIL
    now = datetime.now(timezone("UTC"))

    @property
    def _name(self) -> str:
        """Include date format in the name if feature flag is enabled"""
        return (
            self._parse_name(self._content.name)
            if is_feature_enabled("DATE_FORMAT_IN_EMAIL_SUBJECT")
            else self._content.name
        )

    @staticmethod
    def _get_smtp_domain() -> str:
        return parseaddr(app.config["SMTP_MAIL_FROM"])[1].split("@")[1]

    def _error_template(self, text: str) -> str:
        return __(
            """
            <p>Your report/alert was unable to be generated because of the following error: %(text)s</p>
            <p>Please check your dashboard/chart for errors.</p>
            """,  # noqa: E501
            text=text,
            url=self._content.url,
        )

    def _extract_date(self, tz) -> str:
        from datetime import timedelta
        import pandas as pd
        import io
        
        target_date = datetime.now(tz)
        default_date_str = target_date.strftime("%d-%m-%Y")
        
        def _get_date_from_df(df) -> Optional[str]:
            # Priority 1: Exact matches
            exact_columns = ['BUSINESS_DATE', 'DATE', 'date', 'business_date']
            for col in exact_columns:
                if col in df.columns:
                    val = df[col].dropna().first_valid_index()
                    if val is not None:
                        b_date = df.loc[val, col]
                        parsed_date = pd.to_datetime(b_date, errors='coerce')
                        if pd.notnull(parsed_date):
                            return parsed_date.strftime("%d-%m-%Y")

            # Priority 2: Substring matches containing 'Date', 'date', or 'DATE'
            for col in df.columns:
                str_col = str(col)
                if 'Date' in str_col or 'date' in str_col or 'DATE' in str_col:
                    val = df[col].dropna().first_valid_index()
                    if val is not None:
                        b_date = df.loc[val, col]
                        parsed_date = pd.to_datetime(b_date, errors='coerce')
                        if pd.notnull(parsed_date):
                            return parsed_date.strftime("%d-%m-%Y")
            return None

        try:
            if self._content.embedded_data is not None:
                res = _get_date_from_df(self._content.embedded_data)
                if res:
                    return res
            
            if self._content.csv:
                df = pd.read_csv(io.BytesIO(self._content.csv), nrows=5)
                res = _get_date_from_df(df)
                if res:
                    return res
        except Exception as e:
            logger.warning("Failed to extract date from report data: %s", e)
            
        return default_date_str

    def _get_csv_filename(self) -> str:
        """
        Generate CSV filename following custom naming convention.
        
        Pattern A (default): Report_{Chart_Name}_{Date}.csv
        - Extracts chart name from AUTO_MAIL_ prefix if present
        - Falls back to report name if no chart
        
        Pattern B (override): {EMAIL_SUBJECT_NAME}_{Date}.csv
        - Used when email_subject is provided
        
        Date format: DD-MM-YYYY
        All filenames are sanitized to remove invalid filesystem characters.
        """
        from superset.reports.models import ReportDataFormat
        
        report_schedule = self._content.report_schedule
        
        # Only apply custom naming to CSV files
        if not report_schedule or report_schedule.report_format != ReportDataFormat.CSV:
            # Fallback to original naming for non-CSV
            return __(f"{self._name}.csv")
        
        # Get date from report data or use current date in report timezone - 1 day
        report_timezone = report_schedule.timezone or "UTC"
        tz = timezone(report_timezone)
        date_str = self._extract_date(tz)
        
        # Determine which pattern to use
        if report_schedule.email_subject:
            # Pattern B: Use email_subject
            base_name = report_schedule.email_subject
        else:
            # Pattern A: Extract from chart name
            if report_schedule.chart:
                chart_name = report_schedule.chart.slice_name
                # Extract name after AUTO_MAIL_ prefix
                if chart_name.startswith("AUTO_MAIL_"):
                    chart_name = chart_name[len("AUTO_MAIL_"):]
                base_name = f"Report_{chart_name}"
            else:
                # Fallback for dashboards (shouldn't normally happen for CSV)
                base_name = f"Report_{report_schedule.name}"
        
        # Sanitize the base name
        sanitized_name = sanitize_filename(base_name)
        
        # Return final filename
        return f"{sanitized_name}_{date_str}.csv"

    def _get_content(self) -> EmailContent:
        if self._content.text:
            return EmailContent(body=self._error_template(self._content.text))
        # Get the domain from the 'From' address ..
        # and make a message id without the < > in the end

        domain = self._get_smtp_domain()
        
        images = {}
        data_attachments = {}

        if self._content.screenshots:
            for idx, screenshot in enumerate(self._content.screenshots):
                image_name = __("%(name)s_%(idx)s.png", name=self._name, idx=idx + 1)
                images[image_name] = screenshot

        # Strip any malicious HTML from the description
        # pylint: disable=no-member
        raw_description = self._content.description or ""
        raw_description = raw_description.replace("\n", "<br>")
        description = nh3.clean(
            raw_description,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
        )

        # Strip malicious HTML from embedded data, allowing only table elements
        if self._content.embedded_data is not None:
            df = self._content.embedded_data
            # pylint: disable=no-member
            html_table = nh3.clean(
                df.to_html(na_rep="", index=True, escape=True),
                # pandas will escape the HTML in cells already, so passing
                # more allowed tags here will not work
                tags=TABLE_TAGS,
                attributes=ALLOWED_TABLE_ATTRIBUTES,
            )
        else:
            html_table = ""

        img_tags = []
        for img_name in images.keys():
            img_tags.append(
                f'<div class="image"><img src="cid:{img_name}"></div>'
            )
        img_tags_str = "\n".join(img_tags)

        body = textwrap.dedent(
            f"""
            <html>
              <head>
                <style type="text/css">
                  table, th, td {{
                    border-collapse: collapse;
                    border-color: rgb(200, 212, 227);
                    color: rgb(42, 63, 95);
                    padding: 4px 8px;
                  }}
                  .image{{
                      margin-bottom: 18px;
                      min-width: 1000px;
                  }}
                </style>
              </head>
              <body>
                <div>{description}</div>
                <br>
                {html_table}
                {img_tags_str}
              </body>
            </html>
            """
        )
        
        if self._content.csv:
            csv_filename = self._get_csv_filename()
            if self._content.report_schedule and self._content.report_schedule.extra.get("send_as_zip", True):
                zip_filename = csv_filename.replace(".csv", ".zip")
                data_attachments[zip_filename] = _zip_bytes(csv_filename, self._content.csv)
            else:
                data_attachments[csv_filename] = self._content.csv

        pdf_data = None
        if self._content.pdf:
            pdf_filename = __("%(name)s.pdf", name=self._name)
            pdf_data = {pdf_filename: self._content.pdf}

        return EmailContent(
            body=body,
            images=images,
            pdf=pdf_data,
            data=data_attachments if data_attachments else None,
            header_data=self._content.header_data,
        )

    def _get_subject(self) -> str:
        return __(
            "%(prefix)s %(title)s",
            prefix=app.config["EMAIL_REPORTS_SUBJECT_PREFIX"],
            title=self._name,
        )

    def _parse_name(self, name: str) -> str:
        """If user add a date format to the subject, parse it to the real date
        This feature is hidden behind a feature flag `DATE_FORMAT_IN_EMAIL_SUBJECT`
        by default it is disabled
        """
        return self.now.strftime(name)

    def _get_to(self) -> str:
        return json.loads(self._recipient.recipient_config_json)["target"]

    def _get_cc(self) -> str:
        # To accomadate backward compatability
        return json.loads(self._recipient.recipient_config_json).get("ccTarget", "")

    def _get_bcc(self) -> str:
        # To accomadate backward compatability
        return json.loads(self._recipient.recipient_config_json).get("bccTarget", "")

    @statsd_gauge("reports.email.send")
    def send(self) -> None:
        subject = self._get_subject()
        content = self._get_content()
        to = self._get_to()
        cc = self._get_cc()
        bcc = self._get_bcc()

        try:
            send_email_smtp(
                to,
                subject,
                content.body,
                app.config,
                files=[],
                data=content.data,
                pdf=content.pdf,
                images=content.images,
                mime_subtype="related",
                dryrun=False,
                cc=cc,
                bcc=bcc,
                header_data=content.header_data,
            )
            logger.info(
                "Report sent to email, notification content is %s", content.header_data
            )
        except SupersetErrorsException as ex:
            raise NotificationError(
                ";".join([error.message for error in ex.errors])
            ) from ex
        except Exception as ex:
            raise NotificationError(str(ex)) from ex
