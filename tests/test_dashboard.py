"""Test route dashboard: auth gate + cổng duyệt web."""

import pytest
from starlette.testclient import TestClient

from ytb_pipeline.config import settings as settings_module
from ytb_pipeline.web import approvals
from ytb_pipeline.web.app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "dashboard_password", "pw")
    monkeypatch.setattr(settings_module.settings, "dashboard_secret_key", "test-secret-key")
    return TestClient(create_app())


def test_root_redirects_to_login_when_anonymous(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_wrong_password_rejected(client):
    r = client.post("/login", data={"password": "nope"})
    assert "Sai mật khẩu" in r.text


def test_login_then_dashboard_and_config(client):
    client.post("/login", data={"password": "pw"})
    assert "Chạy pipeline" in client.get("/").text
    assert "Voiceover" in client.get("/config").text


def test_empty_password_setting_blocks_login(monkeypatch):
    monkeypatch.setattr(settings_module.settings, "dashboard_password", "")
    c = TestClient(create_app())
    r = c.post("/login", data={"password": "anything"})
    assert "bị chặn" in r.text


def test_resolve_approval_sets_verdict():
    from ytb_pipeline.web.approvals import _pending, Pending
    item = Pending(id=999, title="t", body="b")
    _pending[999] = item
    assert approvals.resolve(999, approved=True) is True
    assert item.verdict.decision.value == "approved"
    assert approvals.resolve(12345, approved=True) is False
