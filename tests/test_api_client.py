"""Tests for api.client's request/response logging and credential redaction."""
import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.api_logger import redact_body


def test_redact_body_masks_password_fields():
    body = {"email": "a@b.com", "password": "secret123"}
    redacted = redact_body(body)
    assert redacted["email"] == "a@b.com"
    assert redacted["password"] == "***"


def test_redact_body_masks_tokens():
    body = {"access_token": "eyJ...", "refresh_token": "xyz", "token_type": "bearer"}
    redacted = redact_body(body)
    assert redacted["access_token"] == "***"
    assert redacted["refresh_token"] == "***"
    assert redacted["token_type"] == "bearer"


def test_redact_body_passes_through_non_dict():
    assert redact_body(None) is None
    assert redact_body([1, 2, 3]) == [1, 2, 3]


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"{}"):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._json_data = json_data if json_data is not None else {}
        self.content = content

    def json(self):
        return self._json_data


def test_login_request_never_logs_password_or_tokens_in_plaintext(monkeypatch, caplog):
    from api.client import ApiClient
    from api.api_logger import api_logger

    api_logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger="broker_sync.api")
    try:
        client = ApiClient()
        monkeypatch.setattr(
            client._session, "request",
            lambda method, url, **kwargs: _FakeResponse(
                200, {"access_token": "tok-value", "refresh_token": "rtok-value", "token_type": "bearer"},
            ),
        )
        client.post(
            "/auth/login",
            json_body={"email": "a@b.com", "password": "supersecret"},
            auth=False,
        )
    finally:
        api_logger.removeHandler(caplog.handler)

    log_text = caplog.text
    assert "supersecret" not in log_text
    assert "tok-value" not in log_text
    assert "rtok-value" not in log_text
    assert "'password': '***'" in log_text
    assert "'access_token': '***'" in log_text
    assert "'refresh_token': '***'" in log_text


def test_failed_request_logs_status_and_error_code(monkeypatch, caplog):
    from api.client import ApiClient
    from api.api_logger import api_logger
    from api.exceptions import ApiError

    api_logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger="broker_sync.api")
    try:
        client = ApiClient()
        monkeypatch.setattr(
            client._session, "request",
            lambda method, url, **kwargs: _FakeResponse(
                401, {"detail": "Invalid email or password", "code": "invalid_credentials"},
            ),
        )
        try:
            client.post("/auth/login", json_body={"email": "a@b.com", "password": "wrong"}, auth=False)
        except ApiError:
            pass
    finally:
        api_logger.removeHandler(caplog.handler)

    assert "invalid_credentials" in caplog.text
    assert "401" in caplog.text


def test_fastapi_validation_error_list_becomes_a_string(monkeypatch):
    # FastAPI's own request-validation errors use {"detail": [...]} — a list
    # of per-field dicts, no "code" key. ApiError.detail must always end up
    # a str (Qt's QMessageBox.setText rejects anything else and crashes).
    from api.client import ApiClient
    from api.exceptions import ApiError

    client = ApiClient()
    validation_body = {
        "detail": [
            {"type": "string_too_short", "loc": ["body", "rows", 213, "symbol"],
             "msg": "String should have at least 1 character"},
            {"type": "string_too_short", "loc": ["body", "rows", 214, "symbol"],
             "msg": "String should have at least 1 character"},
        ]
    }
    monkeypatch.setattr(
        client._session, "request",
        lambda method, url, **kwargs: _FakeResponse(422, validation_body),
    )

    try:
        client.post("/historic/daily-upload", json_body={"rows": []}, auth=False)
        assert False, "expected ApiError"
    except ApiError as exc:
        assert isinstance(exc.detail, str)
        assert "rows.213.symbol" in exc.detail
        assert "String should have at least 1 character" in exc.detail


def test_non_list_non_string_detail_is_coerced_to_string(monkeypatch):
    from api.client import ApiClient
    from api.exceptions import ApiError

    client = ApiClient()
    monkeypatch.setattr(
        client._session, "request",
        lambda method, url, **kwargs: _FakeResponse(500, {"detail": {"unexpected": "shape"}}),
    )

    try:
        client.get("/data/metrics")
        assert False, "expected ApiError"
    except ApiError as exc:
        assert isinstance(exc.detail, str)
