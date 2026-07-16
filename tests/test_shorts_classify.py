"""Test phân loại Short vs clip ở khâu publish."""

from ytb_pipeline.pkg.models import RenderedVideo
from ytb_pipeline.publish import uploader


def _video(duration: float, video_path=None) -> RenderedVideo:
    return RenderedVideo(topic="t", title="T", description="mô tả",
                         duration_sec=duration, video_path=video_path)


def test_video_doc_ngan_la_short(monkeypatch):
    monkeypatch.setattr(uploader, "_dimensions", lambda p: (1080, 1920))
    assert uploader._is_short(_video(31.8)) is True


def test_video_ngang_dai_khong_phai_short(monkeypatch):
    monkeypatch.setattr(uploader, "_dimensions", lambda p: (1920, 1080))
    assert uploader._is_short(_video(650.0)) is False


def test_video_doc_1_2_phut_van_la_short(monkeypatch):
    # YouTube cho phép Short tới 3 phút; short pipeline nhắm 1–1.5 phút
    monkeypatch.setattr(uploader, "_dimensions", lambda p: (1080, 1920))
    assert uploader._is_short(_video(75.0)) is True
    assert uploader._is_short(_video(93.0)) is True


def test_video_doc_qua_3_phut_khong_phai_short(monkeypatch):
    monkeypatch.setattr(uploader, "_dimensions", lambda p: (1080, 1920))
    assert uploader._is_short(_video(200.0)) is False


def test_khong_do_duoc_kich_thuoc_thi_dua_vao_thoi_luong(monkeypatch):
    monkeypatch.setattr(uploader, "_dimensions", lambda p: (0, 0))
    assert uploader._is_short(_video(90.0)) is True
    assert uploader._is_short(_video(200.0)) is False


def test_them_shorts_tag_khong_trung_lap():
    assert uploader._with_hashtags("abc", ["#Shorts"]).endswith("#Shorts")
    assert uploader._with_hashtags("abc\n\n#Shorts", ["#Shorts"]) == "abc\n\n#Shorts"
    assert uploader._with_hashtags("abc #shorts", ["#Shorts"]).count("#") == 1
