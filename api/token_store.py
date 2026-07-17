# api/token_store.py
"""
In-memory JWT storage, with optional disk persistence for "keep me logged in".

File layout (auth_session.json): {"access_token": "...", "refresh_token": "..."}
"""

import base64
import json
import os

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "auth_session.json")


def _decode_jwt_payload(token: str) -> dict:
    """Reads the claims out of a JWT for display purposes only — the signature
    is already verified server-side on every request, so no need to re-verify
    it here just to show the user's name/email in the UI.
    """
    try:
        payload_b64 = token.split(".")[1]
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


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

    def update_access_token(self, access_token: str) -> None:
        """Swaps in a fresh access token (e.g. after a profile update changes its
        claims) without touching the refresh token or persistence setting.
        """
        self._access_token = access_token
        if self._persist:
            self._save_to_disk()

    def get_refresh_token(self) -> str | None:
        return self._refresh_token

    def get_user_name(self) -> str | None:
        if not self._access_token:
            return None
        return _decode_jwt_payload(self._access_token).get("name")

    def get_user_email(self) -> str | None:
        if not self._access_token:
            return None
        return _decode_jwt_payload(self._access_token).get("email")

    def get_user_phone_number(self) -> str | None:
        if not self._access_token:
            return None
        return _decode_jwt_payload(self._access_token).get("phone_number")

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
