# api/client.py
import time

import requests

from api.api_logger import api_logger, redact_body
from api.config import BASE_URL
from api.endpoints import REFRESH
from api.exceptions import ApiError, NetworkError
from api.token_store import token_manager

_TIMEOUT_SECONDS = 15
_MAX_VALIDATION_ERRORS_SHOWN = 5


def _format_validation_errors(errors: list) -> str:
    """Turns FastAPI's {"detail": [{"loc": [...], "msg": ...}, ...]} shape
    into readable text — a raw dump of hundreds of near-identical per-row
    errors (e.g. one bad file column repeated across every row) would be
    unreadable in a popup, so this caps how many are shown.
    """
    if not errors:
        return "Invalid request"
    lines = []
    for err in errors[:_MAX_VALIDATION_ERRORS_SHOWN]:
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        msg = err.get("msg", "Invalid value")
        lines.append(f"{loc}: {msg}" if loc else msg)
    remaining = len(errors) - _MAX_VALIDATION_ERRORS_SHOWN
    if remaining > 0:
        lines.append(f"...and {remaining} more error(s)")
    return "\n".join(lines)


class ApiClient:
    def __init__(self):
        self._session = requests.Session()
        self._on_session_expired = None

    def set_session_expired_callback(self, callback) -> None:
        self._on_session_expired = callback

    def get(self, path: str, params: dict | None = None, auth: bool = True) -> dict:
        return self._request("GET", path, params=params, auth=auth)

    def post(self, path: str, json_body: dict | None = None, auth: bool = True) -> dict:
        return self._request("POST", path, json_body=json_body, auth=auth)

    def patch(self, path: str, json_body: dict | None = None, auth: bool = True) -> dict:
        return self._request("PATCH", path, json_body=json_body, auth=auth)

    def delete(self, path: str, params: dict | None = None, auth: bool = True) -> dict:
        return self._request("DELETE", path, params=params, auth=auth)

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
        auth: bool = True,
        _retried: bool = False,
    ) -> dict:
        headers = {}
        if auth:
            token = token_manager.get_access_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        api_logger.debug(
            "-> %s %s params=%s body=%s has_token=%s",
            method, path, params, redact_body(json_body), bool(headers.get("Authorization")),
        )
        start = time.monotonic()
        try:
            response = self._session.request(
                method,
                BASE_URL + path,
                params=params,
                json=json_body,
                headers=headers,
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            api_logger.warning(
                "<- %s %s network error after %.0fms: %s",
                method, path, (time.monotonic() - start) * 1000, exc,
            )
            raise NetworkError(f"Could not reach server: {exc}") from exc

        elapsed_ms = (time.monotonic() - start) * 1000

        if response.status_code == 401 and auth and not _retried:
            if self._refresh():
                return self._request(
                    method, path, params=params, json_body=json_body,
                    auth=auth, _retried=True,
                )

        if not response.ok:
            detail, code = self._parse_error(response)
            api_logger.warning(
                "<- %s %s %s (%.0fms) code=%s detail=%s",
                method, path, response.status_code, elapsed_ms, code, detail,
            )
            raise ApiError(detail, code, response.status_code)

        if not response.content:
            api_logger.debug("<- %s %s %s (%.0fms) <empty>", method, path, response.status_code, elapsed_ms)
            return {}
        try:
            body = response.json()
        except requests.exceptions.JSONDecodeError as exc:
            api_logger.warning(
                "<- %s %s %s (%.0fms) invalid JSON: %s",
                method, path, response.status_code, elapsed_ms, exc,
            )
            raise NetworkError(f"Invalid response from server: {exc}") from exc

        api_logger.debug(
            "<- %s %s %s (%.0fms) body=%s",
            method, path, response.status_code, elapsed_ms, redact_body(body),
        )
        return body

    def _refresh(self) -> bool:
        refresh_token = token_manager.get_refresh_token()
        if not refresh_token:
            return False
        api_logger.debug("-> POST %s (token refresh)", REFRESH)
        start = time.monotonic()
        try:
            response = self._session.post(
                BASE_URL + REFRESH,
                json={"refresh_token": refresh_token},
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            api_logger.warning("<- POST %s network error: %s", REFRESH, exc)
            return False
        elapsed_ms = (time.monotonic() - start) * 1000
        if not response.ok:
            api_logger.warning(
                "<- POST %s %s (%.0fms) refresh failed", REFRESH, response.status_code, elapsed_ms,
            )
            token_manager.clear()
            self._notify_session_expired()
            return False
        try:
            body = response.json()
            access_token = body["access_token"]
            refresh_token_value = body["refresh_token"]
        except (requests.exceptions.JSONDecodeError, KeyError) as exc:
            api_logger.warning(
                "<- POST %s %s (%.0fms) malformed refresh response: %s",
                REFRESH, response.status_code, elapsed_ms, exc,
            )
            return False
        was_persisted = token_manager.is_persisted()
        token_manager.set(access_token, refresh_token_value, persist=was_persisted)
        api_logger.debug("<- POST %s %s (%.0fms) refreshed", REFRESH, response.status_code, elapsed_ms)
        return True

    def _notify_session_expired(self) -> None:
        if self._on_session_expired is None:
            return
        try:
            self._on_session_expired()
        except Exception:
            pass

    @staticmethod
    def _parse_error(response: requests.Response) -> tuple[str, str]:
        try:
            body = response.json()
        except Exception:
            return f"Server error ({response.status_code})", "unknown_error"

        detail = body.get("detail", "Unknown error")
        code = body.get("code", "unknown_error")
        # FastAPI's own request-validation errors (missing/malformed fields)
        # use {"detail": [...]} — a list of per-field error dicts, no "code"
        # key — distinct from this app's domain-error shape. ApiError.detail
        # must always be a string (Qt's setText rejects anything else), so
        # that shape is collapsed into readable text here rather than left
        # for every call site to guard against.
        if isinstance(detail, list):
            detail = _format_validation_errors(detail)
        elif not isinstance(detail, str):
            detail = str(detail)
        return detail, code


api_client = ApiClient()
