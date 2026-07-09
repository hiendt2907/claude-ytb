"""Test tạo thư mục mới qua file browser (dùng khi chọn output_dir)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ytb_pipeline.webui import app as app_module
from ytb_pipeline.webui.browse import make_directory


def test_make_directory_creates_subfolder(tmp_path: Path) -> None:
    new_dir = make_directory(tmp_path, "new_output")
    assert new_dir == tmp_path / "new_output"
    assert new_dir.is_dir()


def test_make_directory_is_idempotent(tmp_path: Path) -> None:
    make_directory(tmp_path, "existing")
    new_dir = make_directory(tmp_path, "existing")
    assert new_dir.is_dir()


@pytest.mark.parametrize("bad_name", ["", "  ", "..", ".", "a/b", "a\\b"])
def test_make_directory_rejects_invalid_names(tmp_path: Path, bad_name: str) -> None:
    with pytest.raises(ValueError):
        make_directory(tmp_path, bad_name)


def test_make_directory_rejects_non_directory_parent(tmp_path: Path) -> None:
    file_path = tmp_path / "f.txt"
    file_path.write_bytes(b"")
    with pytest.raises(NotADirectoryError):
        make_directory(file_path, "x")


def test_mkdir_endpoint_creates_folder(tmp_path: Path) -> None:
    client = TestClient(app_module.app)
    res = client.post(
        "/api/browse/mkdir", data={"parent": str(tmp_path), "name": "new_folder"}
    )
    assert res.status_code == 200
    assert Path(res.json()["path"]).is_dir()


def test_mkdir_endpoint_rejects_bad_name(tmp_path: Path) -> None:
    client = TestClient(app_module.app)
    res = client.post("/api/browse/mkdir", data={"parent": str(tmp_path), "name": ".."})
    assert res.status_code == 400
