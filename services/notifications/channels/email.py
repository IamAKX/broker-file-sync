"""
Delivers notifications by email via the backend's SMTP-backed endpoint
(broker-sync-api's app/services/email_service.py). The recipient is always
the logged-in user's registered email — the backend resolves it from the
bearer token itself, so this channel never carries an address.

Network/API failures are swallowed rather than raised: this channel runs
inside NotificationService.notify() alongside SystemChannel, and a mail
delivery hiccup (no connectivity, expired session) must not stop the tray
notification other channels still deliver, or crash the caller (often a
background scheduled job already mid-failure-report — see
services/scheduled_jobs.py).

send() dispatches to a small background thread pool instead of calling the
network directly. notify() (and this channel with it) is called from the GUI
thread — screens/live_viewer.py's _run_strategy_alert_checks loops over every
strategy-alert event on a single tick and calls it once per event — and
notifications_api.send_email is a real HTTP round trip with up to 15s
(api.client._TIMEOUT_SECONDS) to fail. Calling it inline used to serialize
those round trips on the GUI thread: several alerts firing on the same tick
(a market-wide move crossing several strategies' triggers at once, entirely
plausible) froze the whole app — Live Master View included — for the sum of
every alert's timeout. Dispatching means the loop that calls send() for each
event returns immediately regardless of how slow (or unreachable) the mail
endpoint is.
"""

import concurrent.futures

from api import notifications_api
from api.exceptions import ApiError, NetworkError
from services.error_logging import error_logger
from services.notifications.channels.base import NotificationChannel
from services.notifications.payload import NotificationPayload

# One shared, small pool for the app's lifetime — email notifications are
# infrequent and not latency-sensitive to each other, so there's no need for
# more than a couple of workers; this just needs to exist off the GUI thread.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="email-notify")


class EmailChannel(NotificationChannel):
    CHANNEL_ID = "email"

    def send(self, payload: NotificationPayload) -> concurrent.futures.Future:
        """Returns the submitted Future — ignored by NotificationService's
        plain `channel.send(payload)` call, but lets tests (and any other
        caller that cares) wait for delivery to actually finish instead of
        just assuming it did."""
        return _executor.submit(self._send_now, payload.title, payload.message)

    @staticmethod
    def _send_now(title: str, message: str) -> None:
        try:
            notifications_api.send_email(title, message)
        except (ApiError, NetworkError) as exc:
            error_logger.error("Email notification delivery failed: %s", exc)
        except Exception as exc:   # noqa: BLE001
            # Deliberately broader than the ApiError/NetworkError above.
            # This runs on a background thread (see send()) with nothing
            # downstream ever calling .result() on the Future in production
            # — before send() was dispatched to a thread, ANY exception here
            # propagated up to whatever caught it inline (e.g. live_viewer's
            # per-tick guard), so it was at least visible somewhere. Now, an
            # exception that isn't ApiError/NetworkError (a bug in this
            # module, an unexpected response shape, anything) would
            # otherwise vanish into the Future with zero trace of email
            # having silently stopped working.
            error_logger.exception("Email notification delivery failed unexpectedly: %s", exc)
