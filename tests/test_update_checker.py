"""Tests for services.update_checker — version parsing/comparison, GitHub
release parsing, checksum verification, download, and zip staging. The
actual detached helper-script launch (stage_and_apply's final step) is not
covered here — it kills/replaces a running process's own files and isn't
something a unit test should attempt; see the module docstring.
"""
import sys
import os
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services import update_checker as uc


# ── semver parsing ──────────────────────────────────────────────────────────

def test_parse_semver_with_v_prefix():
    assert uc._parse_semver("v1.2.3") == (1, 2, 3)


def test_parse_semver_without_v_prefix():
    assert uc._parse_semver("1.2.3") == (1, 2, 3)


def test_parse_semver_malformed_returns_none():
    assert uc._parse_semver("build-42") is None
    assert uc._parse_semver("") is None
    assert uc._parse_semver(None) is None


# ── has_update ───────────────────────────────────────────────────────────────

def test_has_update_true_when_release_is_newer(monkeypatch):
    monkeypatch.setattr(uc, "APP_VERSION", "1.0.0")
    release = {"version_tuple": (1, 1, 0)}
    assert uc.has_update(release) is True


def test_has_update_false_when_up_to_date(monkeypatch):
    monkeypatch.setattr(uc, "APP_VERSION", "1.1.0")
    release = {"version_tuple": (1, 1, 0)}
    assert uc.has_update(release) is False


def test_has_update_false_when_release_is_older(monkeypatch):
    monkeypatch.setattr(uc, "APP_VERSION", "2.0.0")
    release = {"version_tuple": (1, 1, 0)}
    assert uc.has_update(release) is False


def test_has_update_true_for_dev_build(monkeypatch):
    monkeypatch.setattr(uc, "APP_VERSION", "0.0.0-dev")
    # "0.0.0-dev" actually parses (leading digits match) — use a truly
    # unparseable placeholder to exercise the "current is None" branch.
    monkeypatch.setattr(uc, "_parse_semver", lambda tag: None if tag == "0.0.0-dev" else (9, 9, 9))
    release = {"version_tuple": (1, 0, 0)}
    assert uc.has_update(release) is True


def test_is_frozen_reflects_sys_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert uc.is_frozen() is False
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert uc.is_frozen() is True


# ── fetch_latest_release ─────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, json_data=None, status=200, raise_exc=None, text=""):
        self._json = json_data
        self.status_code = status
        self._raise_exc = raise_exc
        self.text = text
        self.headers = {}

    def raise_for_status(self):
        if self._raise_exc:
            raise self._raise_exc

    def json(self):
        return self._json


def test_fetch_latest_release_parses_windows_asset(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    data = {
        "tag_name": "v1.4.0",
        "body": "release notes here",
        "html_url": "https://github.com/x/y/releases/tag/v1.4.0",
        "assets": [
            {"name": "BrokerFileSync-windows.zip", "browser_download_url": "https://dl/win.zip"},
            {"name": "BrokerFileSync-macos.zip", "browser_download_url": "https://dl/mac.zip"},
            {"name": "checksums.txt", "browser_download_url": "https://dl/checksums.txt"},
        ],
    }
    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: _FakeResponse(data))

    release = uc.fetch_latest_release()
    assert release["version"] == "1.4.0"
    assert release["version_tuple"] == (1, 4, 0)
    assert release["asset_name"] == "BrokerFileSync-windows.zip"
    assert release["asset_url"] == "https://dl/win.zip"
    assert release["checksum_url"] == "https://dl/checksums.txt"
    assert release["notes"] == "release notes here"


def test_fetch_latest_release_no_asset_for_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    data = {"tag_name": "v1.0.0", "assets": []}
    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: _FakeResponse(data))
    release = uc.fetch_latest_release()
    assert release["asset_url"] is None


def test_fetch_latest_release_malformed_tag_raises(monkeypatch):
    data = {"tag_name": "build-42", "assets": []}
    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: _FakeResponse(data))
    with pytest.raises(uc.UpdateCheckError):
        uc.fetch_latest_release()


def test_fetch_latest_release_network_error_raises(monkeypatch):
    def _boom(*a, **k):
        raise uc.requests.RequestException("connection refused")
    monkeypatch.setattr(uc.requests, "get", _boom)
    with pytest.raises(uc.UpdateCheckError):
        uc.fetch_latest_release()


def test_fetch_latest_release_bad_json_raises(monkeypatch):
    class _BadJson(_FakeResponse):
        def json(self):
            raise ValueError("not json")
    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: _BadJson())
    with pytest.raises(uc.UpdateCheckError):
        uc.fetch_latest_release()


# ── download_asset ───────────────────────────────────────────────────────────

def test_download_asset_writes_file_and_reports_progress(tmp_path, monkeypatch):
    body = b"x" * 1000

    class _StreamResponse(_FakeResponse):
        def __init__(self):
            super().__init__()
            self.headers = {"Content-Length": str(len(body))}

        def iter_content(self, chunk_size):
            for i in range(0, len(body), chunk_size):
                yield body[i:i + chunk_size]

    monkeypatch.setattr(uc.requests, "get", lambda *a, **k: _StreamResponse())

    progress_calls = []
    release = {"asset_url": "https://dl/x.zip", "asset_name": "x.zip"}
    path = uc.download_asset(release, tmp_path, progress_cb=lambda w, t: progress_calls.append((w, t)))

    assert path.read_bytes() == body
    assert progress_calls[-1] == (1000, 1000)


def test_download_asset_no_url_raises_not_supported(tmp_path):
    release = {"asset_url": None, "asset_name": None}
    with pytest.raises(uc.UpdateNotSupported):
        uc.download_asset(release, tmp_path)


# ── verify_checksum ──────────────────────────────────────────────────────────

def test_verify_checksum_matches(tmp_path, monkeypatch):
    f = tmp_path / "x.zip"
    f.write_bytes(b"hello world")
    import hashlib
    digest = hashlib.sha256(b"hello world").hexdigest()

    monkeypatch.setattr(
        uc.requests, "get",
        lambda *a, **k: _FakeResponse(text=f"{digest}  x.zip\n"),
    )
    release = {"checksum_url": "https://dl/checksums.txt", "asset_name": "x.zip"}
    assert uc.verify_checksum(release, f) is True


def test_verify_checksum_mismatch(tmp_path, monkeypatch):
    f = tmp_path / "x.zip"
    f.write_bytes(b"hello world")
    monkeypatch.setattr(
        uc.requests, "get",
        lambda *a, **k: _FakeResponse(text="deadbeef  x.zip\n"),
    )
    release = {"checksum_url": "https://dl/checksums.txt", "asset_name": "x.zip"}
    assert uc.verify_checksum(release, f) is False


def test_verify_checksum_no_checksum_url_skips_verification(tmp_path):
    f = tmp_path / "x.zip"
    f.write_bytes(b"anything")
    release = {"checksum_url": None, "asset_name": "x.zip"}
    assert uc.verify_checksum(release, f) is True


def test_verify_checksum_filename_not_listed_skips_verification(tmp_path, monkeypatch):
    f = tmp_path / "x.zip"
    f.write_bytes(b"anything")
    monkeypatch.setattr(
        uc.requests, "get",
        lambda *a, **k: _FakeResponse(text="deadbeef  some-other-file.zip\n"),
    )
    release = {"checksum_url": "https://dl/checksums.txt", "asset_name": "x.zip"}
    assert uc.verify_checksum(release, f) is True


# ── _extract_staged_root (zip staging, both platform shapes) ────────────────

def _make_zip(path, entries: dict):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)


def test_extract_staged_root_windows_flat(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    zip_path = tmp_path / "win.zip"
    _make_zip(zip_path, {"BrokerFileSync.exe": "exe", "lib/foo.dll": "dll"})
    staging = tmp_path / "staging"
    staging.mkdir()

    root = uc._extract_staged_root(zip_path, staging)
    assert root == staging
    assert (root / "BrokerFileSync.exe").exists()


def test_extract_staged_root_windows_missing_exe_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    zip_path = tmp_path / "win.zip"
    _make_zip(zip_path, {"readme.txt": "hi"})
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(uc.UpdateApplyError):
        uc._extract_staged_root(zip_path, staging)


def test_extract_staged_root_macos_app_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    zip_path = tmp_path / "mac.zip"
    _make_zip(zip_path, {"BrokerFileSync.app/Contents/MacOS/BrokerFileSync": "exe"})
    staging = tmp_path / "staging"
    staging.mkdir()

    root = uc._extract_staged_root(zip_path, staging)
    assert root == staging / "BrokerFileSync.app"


def test_extract_staged_root_macos_missing_bundle_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    zip_path = tmp_path / "mac.zip"
    _make_zip(zip_path, {"readme.txt": "hi"})
    staging = tmp_path / "staging"
    staging.mkdir()
    with pytest.raises(uc.UpdateApplyError):
        uc._extract_staged_root(zip_path, staging)


# ── stage_and_apply guards ───────────────────────────────────────────────────

def test_stage_and_apply_refuses_when_not_frozen(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    with pytest.raises(uc.UpdateNotSupported):
        uc.stage_and_apply(tmp_path / "whatever.zip")
