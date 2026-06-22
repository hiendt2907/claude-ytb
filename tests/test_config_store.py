"""Test config động: ghi data/config.json + reload singleton trong tiến trình."""

import json

import pytest

from ytb_pipeline.config import settings as settings_module
from ytb_pipeline.web import config_store


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Trỏ config động vào tmp + khôi phục singleton sau test.

    Patch cả _config_path (ghi) lẫn model_config['json_file'] (reload đọc lại).
    """
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "_config_path", lambda: cfg)
    original_json_file = config_store.Settings.model_config.get("json_file")
    config_store.Settings.model_config["json_file"] = str(cfg)
    snapshot = dict(settings_module.settings.__dict__)
    yield cfg
    config_store.Settings.model_config["json_file"] = original_json_file
    settings_module.settings.__dict__.clear()
    settings_module.settings.__dict__.update(snapshot)


def test_save_writes_json_and_reloads_singleton(isolated_config):
    changed = config_store.save({"render_provider": "ai", "dashboard_port": "9000"})

    assert "render_provider" in changed
    saved = json.loads(isolated_config.read_text())
    assert saved["render_provider"] == "ai"
    assert saved["dashboard_port"] == 9000
    assert settings_module.settings.render_provider == "ai"
    assert settings_module.settings.dashboard_port == 9000


def test_bool_unchecked_becomes_false(isolated_config):
    config_store.save({"render_provider": "slide"})
    saved = json.loads(isolated_config.read_text())
    assert saved["dry_run"] is False


def test_empty_secret_keeps_old_value(isolated_config):
    config_store.save({"elevenlabs_api_key": "secret-123"})
    assert json.loads(isolated_config.read_text())["elevenlabs_api_key"] == "secret-123"

    config_store.save({"elevenlabs_api_key": ""})
    assert json.loads(isolated_config.read_text())["elevenlabs_api_key"] == "secret-123"


def test_public_value_masks_secret(isolated_config):
    config_store.save({"telegram_bot_token": "abc"})
    field = next(f for f in config_store.FIELDS if f.name == "telegram_bot_token")
    assert config_store.public_value(field) == "••••••••"


def test_read_overrides_empty_when_missing(isolated_config):
    assert config_store.read_overrides() == {}
