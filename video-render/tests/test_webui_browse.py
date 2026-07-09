"""Test cho file browser API (thay thế nhập path tay)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ytb_pipeline.webui import app as app_module
from ytb_pipeline.webui.browse import list_directory


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_list_directory_hides_non_media_files(tmp_path: Path) -> None:
    _touch(tmp_path / "clip.mp4")
    _touch(tmp_path / "notes.txt")
    (tmp_path / "subdir").mkdir()

    listing = list_directory(tmp_path)

    names = {e.name for e in listing.entries}
    assert names == {"clip.mp4", "subdir"}


def test_list_directory_only_dirs_hides_all_files(tmp_path: Path) -> None:
    _touch(tmp_path / "clip.mp4")
    (tmp_path / "subdir").mkdir()

    listing = list_directory(tmp_path, only_dirs=True)

    names = {e.name for e in listing.entries}
    assert names == {"subdir"}


def test_list_directory_rejects_non_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "f.mp4"
    _touch(file_path)

    with pytest.raises(NotADirectoryError):
        list_directory(file_path)


def test_browse_endpoint_lists_entries(tmp_path: Path) -> None:
    _touch(tmp_path / "clip.mp4")
    client = TestClient(app_module.app)

    res = client.get("/api/browse", params={"path": str(tmp_path)})

    assert res.status_code == 200
    body = res.json()
    assert body["current_path"] == str(tmp_path)
    assert any(e["name"] == "clip.mp4" for e in body["entries"])


def test_browse_endpoint_rejects_missing_path() -> None:
    client = TestClient(app_module.app)
    res = client.get("/api/browse", params={"path": "/no/such/dir"})
    assert res.status_code == 400


def test_browse_endpoint_rejects_permission_error(monkeypatch, tmp_path: Path) -> None:
    def fake_list_directory(path, only_dirs=False):  # noqa: ANN001, ARG001
        raise PermissionError("blocked")

    monkeypatch.setattr(app_module, "list_directory", fake_list_directory)
    client = TestClient(app_module.app)

    res = client.get("/api/browse", params={"path": str(tmp_path)})

    assert res.status_code == 400
    assert "Không có quyền" in res.json()["detail"]
