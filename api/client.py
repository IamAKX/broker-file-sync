# api/client.py
import requests

from api.config import BASE_URL
from api.endpoints import REFRESH
from api.exceptions import ApiError, NetworkError
from api.token_store import token_manager

_TIMEOUT_SECONDS = 15


class ApiClient:
    def __init__(self):
        self._session = requests.Session()

    def get(self, path: str, params: dict | None = None, auth: bool = True) -> dict:
        return self._request("GET", path, params=params, auth=auth)

    def post(self, path: str, json_body: dict | None = None, auth: bool = True) -> dict:
        return self._request("POST", path, json_body=json_body, auth=auth)

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
            raise NetworkError(f"Could not reach server: {exc}") from exc

        if response.status_code == 401 and auth and not _retried:
            if self._refresh():
                return self._request(
                    method, path, params=params, json_body=json_body,
                    auth=auth, _retried=True,
                )

        if not response.ok:
            detail, code = self._parse_error(response)
            raise ApiError(detail, code, response.status_code)

        if not response.content:
            return {}
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError as exc:
            raise NetworkError(f"Invalid response from server: {exc}") from exc

    def _refresh(self) -> bool:
        refresh_token = token_manager.get_refresh_token()
        if not refresh_token:
            return False
        try:
            response = self._session.post(
                BASE_URL + REFRESH,
                json={"refresh_token": refresh_token},
                timeout=_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            return False
        if not response.ok:
            token_manager.clear()
            return False
        try:
            body = response.json()
            access_token = body["access_token"]
            refresh_token_value = body["refresh_token"]
        except (requests.exceptions.JSONDecodeError, KeyError):
            return False
        was_persisted = token_manager.get_refresh_token() is not None
        token_manager.set(access_token, refresh_token_value, persist=was_persisted)
        return True

    @staticmethod
    def _parse_error(response: requests.Response) -> tuple[str, str]:
        try:
            body = response.json()
            return body.get("detail", "Unknown error"), body.get("code", "unknown_error")
        except Exception:
            return f"Server error ({response.status_code})", "unknown_error"


api_client = ApiClient()
