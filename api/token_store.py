# api/token_store.py
"""
In-memory JWT storage, with optional disk persistence for "keep me logged in".

File layout (auth_session.json): {"access_token": "...", "refresh_token": "..."}
"""

import json
import os

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "auth_session.json")


class TokenManager:
    def __init__(self):
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._persist: bool = False

    def set(self, access_token: str, refresh_token: str, persist: bool) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._persist = persist
        if persist:
            self._save_to_disk()
        else:
            self._delete_from_disk()

    def get_access_token(self) -> str | None:
        return self._access_token

    def get_refresh_token(self) -> str | None:
        return self._refresh_token

    def is_logged_in(self) -> bool:
        return self._access_token is not None

    def is_persisted(self) -> bool:
        return self._persist

    def clear(self) -> None:
        self._access_token = None
        self._refresh_token = None
        self._persist = False
        self._delete_from_disk()

    def load_persisted(self) -> bool:
        if not os.path.exists(_STORE_FILE):
            return False
        try:
            with open(_STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            access = data.get("access_token")
            refresh = data.get("refresh_token")
            if not access or not refresh:
                return False
            self._access_token = access
            self._refresh_token = refresh
            self._persist = True
            return True
        except Exception:
            return False

    def _save_to_disk(self) -> None:
        with open(_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"access_token": self._access_token, "refresh_token": self._refresh_token},
                f,
            )

    def _delete_from_disk(self) -> None:
        if os.path.exists(_STORE_FILE):
            os.remove(_STORE_FILE)


token_manager = TokenManager()
