# api/reports_api.py
"""Backend client for the Reports feature's "Email" action — uploads a
generated report PDF as a multipart/form-data attachment (see
broker-sync-api's app/routers/notifications.py::send_report_email). Unlike
notifications_api.send_email, the recipient list here is caller-supplied
(a report's OWN recipients — services/report_recipients.py — not the
account-level notification setting)."""

from api.client import api_client
from api.endpoints import NOTIFICATIONS_EMAIL_SEND_REPORT

# SMTP send itself can take several seconds beyond the app's normal 15s
# request ceiling, on top of the upload — matches api.inception_api.
# sync_vendor_data's own rationale for a per-call timeout override.
_SEND_REPORT_TIMEOUT_SECONDS = 40


def send_report_email(pdf_path: str, recipients: list[str], subject: str) -> None:
    """Reads *pdf_path* and uploads it as an attachment to be emailed to
    *recipients* (";"-joined server-side into the request the same way the
    desktop client's own recipient fields already are). Raises ApiError on
    a rejected request (no valid recipients, non-PDF, oversized) or
    NetworkError/ApiError(502) on a real delivery failure."""
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    api_client.post_multipart(
        NOTIFICATIONS_EMAIL_SEND_REPORT,
        data={"recipients": ";".join(recipients), "subject": subject},
        files={"attachment": ("report.pdf", pdf_bytes, "application/pdf")},
        timeout=_SEND_REPORT_TIMEOUT_SECONDS,
    )
