"""Test OAuth helper (publish/youtube_auth.py) — không gọi Google thật.

Mock Credentials/InstalledAppFlow/telegram ở ranh giới module.
"""

from __future__ import annotations

import pytest

from ytb_pipeline.publish import youtube_auth as auth


class _FakeCreds:
    def __init__(self, *, valid=False, expired=True, refresh_token="rt", raise_on_refresh=None):
        self.valid = valid
        self.expired = expired
        self.refresh_token = refresh_token
        self._raise_on_refresh = raise_on_refresh
        self.refreshed = False

    def refresh(self, request):
        if self._raise_on_refresh:
            raise self._raise_on_refresh
        self.refreshed = True
        self.valid = True

    def to_json(self):
        return "{}"


@pytest.fixture(autouse=True)
def _capture_telegram(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(auth.telegram, "send_message", lambda t: sent.append(t))
    return sent


def test_load_or_authorize_returns_valid_creds_without_refresh(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *a, **kw: _FakeCreds(valid=True))

    creds = auth._load_or_authorize(str(token_path), [])

    assert creds.valid is True


def test_load_or_authorize_refreshes_expired_token(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    fake = _FakeCreds(valid=False, expired=True, refresh_token="rt")
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *a, **kw: fake)

    creds = auth._load_or_authorize(str(token_path), [])

    assert creds.refreshed is True


def test_load_or_authorize_raises_reauth_required_when_non_interactive(tmp_path, monkeypatch, _capture_telegram):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    fake = _FakeCreds(valid=False, expired=True, refresh_token="rt", raise_on_refresh=auth.RefreshError("invalid_grant"))
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *a, **kw: fake)

    with pytest.raises(auth.ReauthRequiredError):
        auth._load_or_authorize(str(token_path), [], allow_interactive=False)

    assert len(_capture_telegram) == 1
    assert "ytb auth" in _capture_telegram[0]


def test_load_or_authorize_does_not_crash_when_telegram_unconfigured(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    fake = _FakeCreds(valid=False, expired=True, refresh_token="rt", raise_on_refresh=auth.RefreshError("invalid_grant"))
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *a, **kw: fake)

    def boom(text):
        raise RuntimeError("Thiếu TELEGRAM_BOT_TOKEN")

    monkeypatch.setattr(auth.telegram, "send_message", boom)

    with pytest.raises(auth.ReauthRequiredError):
        auth._load_or_authorize(str(token_path), [], allow_interactive=False)


def test_load_or_authorize_opens_browser_when_interactive_allowed(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    secrets_path = tmp_path / "client_secret.json"
    secrets_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth.settings, "youtube_client_secrets", str(secrets_path))

    fake = _FakeCreds(valid=False, expired=True, refresh_token="rt", raise_on_refresh=auth.RefreshError("invalid_grant"))
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *a, **kw: fake)

    new_creds = _FakeCreds(valid=True)

    class _FakeFlow:
        def run_local_server(self, port):
            return new_creds

    monkeypatch.setattr(
        auth.InstalledAppFlow, "from_client_secrets_file", lambda *a, **kw: _FakeFlow()
    )

    creds = auth._load_or_authorize(str(token_path), [], allow_interactive=True)

    assert creds is new_creds


def test_load_or_authorize_missing_secrets_file_raises(tmp_path, monkeypatch):
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth.settings, "youtube_client_secrets", str(tmp_path / "does_not_exist.json"))
    fake = _FakeCreds(valid=False, expired=True, refresh_token="rt", raise_on_refresh=auth.RefreshError("invalid_grant"))
    monkeypatch.setattr(auth.Credentials, "from_authorized_user_file", lambda *a, **kw: fake)

    with pytest.raises(FileNotFoundError):
        auth._load_or_authorize(str(token_path), [], allow_interactive=True)
