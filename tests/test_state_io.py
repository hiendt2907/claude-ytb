from __future__ import annotations

import json

import pytest

from ytb_pipeline.orchestrator.state_io import atomic_write_json, locked_json_update


def test_atomic_write_json_replaces_existing_file_without_temp_leftover(tmp_path):
    path = tmp_path / "auto_state.json"
    path.write_text('{"old": true}', encoding="utf-8")

    atomic_write_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert not path.with_name("auto_state.json.tmp").exists()


def test_locked_json_update_serializes_read_modify_write(tmp_path):
    path = tmp_path / "auto_state.json"
    path.write_text('{"items": []}', encoding="utf-8")

    with locked_json_update(path) as data:
        data["items"].append("first")

    assert json.loads(path.read_text(encoding="utf-8")) == {"items": ["first"]}


def test_locked_json_update_does_not_write_when_body_fails(tmp_path):
    path = tmp_path / "auto_state.json"
    path.write_text('{"items": []}', encoding="utf-8")

    with pytest.raises(RuntimeError):
        with locked_json_update(path) as data:
            data["items"].append("not persisted")
            raise RuntimeError("abort")

    assert json.loads(path.read_text(encoding="utf-8")) == {"items": []}
