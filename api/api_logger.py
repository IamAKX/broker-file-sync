# api/api_logger.py
"""Request/response logging for ApiClient.

Writes to stdout (visible in the terminal when running via python main.py /
run.sh). Credentials and tokens are redacted before anything is logged, so
console output is safe to share when debugging.
"""

import logging
import sys

# Keys never written verbatim, in request or response bodies — passwords and
# live tokens must never end up in console output that might get shared for
# debugging.
_SENSITIVE_KEYS = {
    "password", "current_password", "new_password",
    "access_token", "refresh_token",
}


def redact_body(body):
    """Shallow-redacts known-sensitive keys in a request/response dict.
    Non-dict bodies (e.g. None, lists) pass through unchanged.
    """
    if not isinstance(body, dict):
        return body
    return {k: ("***" if k in _SENSITIVE_KEYS else v) for k, v in body.items()}


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("broker_sync.api")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False
    return logger


api_logger = _build_logger()
