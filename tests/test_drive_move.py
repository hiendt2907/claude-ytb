"""Test MOVE lên Drive: xoá local sau khi Drive nhận file, giữ local nếu lỗi."""

import pytest

from ytb_pipeline.publish import drive


class _FakeFiles:
    def __init__(self, returned_id="id123"):
        self._id = returned_id

    def list(self, **k):
        return _Exec({"files": [{"id": "folder1", "name": "Claude-YTB"}]})

    def create(self, **k):
        body = {"id": self._id, "webViewLink": "https://drive/x"} if self._id else {}
        return _Exec(body)


class _Exec:
    def __init__(self, val):
        self._val = val

    def execute(self):
        return self._val


class _FakeDrive:
    def __init__(self, returned_id="id123"):
        self._files = _FakeFiles(returned_id)

    def files(self):
        return self._files


def _patch(monkeypatch, drive_obj):
    monkeypatch.setattr(drive, "_ensure_folder", lambda d, name: "folder1")
    import ytb_pipeline.publish.youtube_auth as ya
    monkeypatch.setattr(ya, "get_drive_client", lambda: drive_obj)


def test_move_xoa_local_khi_drive_nhan_file(monkeypatch, tmp_path):
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"data")
    _patch(monkeypatch, _FakeDrive(returned_id="id123"))

    link = drive.backup_to_drive(vid, move=True)

    assert link == "https://drive/x"
    assert not vid.exists()  # đã move -> local bị xoá


def test_khong_move_thi_giu_local(monkeypatch, tmp_path):
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"data")
    _patch(monkeypatch, _FakeDrive(returned_id="id123"))

    drive.backup_to_drive(vid, move=False)

    assert vid.exists()  # backup thường -> giữ local


def test_fail_fast_khi_thieu_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        drive.backup_to_drive(tmp_path / "khong-co.mp4", move=True)
