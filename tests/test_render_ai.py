"""Test khâu render-ai: chọn B-roll đúng hướng, fail-fast thiếu key, overlay RGBA."""

import pytest

from ytb_pipeline.config.settings import settings
from ytb_pipeline.pkg.models import Segment, Voiceover
from ytb_pipeline.render import compose_ai, stock


def test_best_file_uu_tien_video_doc_gan_muc_tieu():
    # Arrange — 1 file ngang nhỏ, 1 file dọc gần 1080x1920
    files = [
        {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "ngang"},
        {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "doc"},
    ]
    # Act
    best = stock._best_file(files, landscape=False)
    # Assert
    assert best["link"] == "doc"


def test_best_file_landscape_uu_tien_video_ngang():
    files = [
        {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "ngang"},
        {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "doc"},
    ]
    best = stock._best_file(files, landscape=True)
    assert best["link"] == "ngang"


def test_best_file_tra_none_khi_khong_co_mp4():
    assert stock._best_file(
        [{"file_type": "image/jpeg", "width": 10, "height": 20}], landscape=False
    ) is None


def test_fetch_broll_fail_fast_khi_thieu_key(monkeypatch):
    # Arrange — ép key rỗng
    monkeypatch.setattr(settings, "pexels_api_key", "")
    # Act / Assert
    with pytest.raises(RuntimeError, match="PEXELS_API_KEY"):
        stock.fetch_broll("anything")


def test_static_overlay_code_la_rgba_dung_kich_thuoc_doc():
    seg = Segment(caption="Xem lại thao tác", narration="...", code="git reflog")
    img = compose_ai._static_overlay(seg, index=1, total=7, dims=(1080, 1920))
    assert img.mode == "RGBA"
    assert img.size == (1080, 1920)


def test_base_overlay_caption_o_lower_third():
    # dải nền + chữ phải ở nửa dưới khung
    _, line_h, lines, y0 = compose_ai._caption_layout(
        "Buổi sáng bắt đầu thế nào", dims=(1080, 1920))
    assert y0 > 1920 // 2
    img = compose_ai._base_overlay("Buổi sáng bắt đầu thế nào",
                                   dims=(1080, 1920), badge="1/5")
    assert img.mode == "RGBA"
    assert img.size == (1080, 1920)


def test_text_overlay_chi_chua_chu_kich_thuoc_dung():
    img = compose_ai._text_overlay("Lưu lại", "Lưu lại kẻo quên",
                                   dims=(1080, 1920))
    assert img.mode == "RGBA"
    assert img.size == (1080, 1920)


def test_brightness_boost_duong_de_bu_sang_broll():
    # BRIGHTNESS_BOOST dương để bù sáng B-roll (VEIL đã giảm còn ~22%)
    assert compose_ai.BRIGHTNESS_BOOST > 0.0


def test_dims_theo_orientation(monkeypatch):
    monkeypatch.setattr(settings, "orientation", "landscape")
    assert compose_ai._dims() == (1920, 1080, True)
    monkeypatch.setattr(settings, "orientation", "portrait")
    assert compose_ai._dims() == (1080, 1920, False)


def test_local_image_cache_key_includes_provider_version(monkeypatch, tmp_path):
    class FakeProvider:
        name = "pillow"
        cache_version = "scene-test"

        def generate(self, prompt, width, height, output_path, **kwargs):
            output_path.write_bytes(b"not-a-real-image")
            return output_path

    monkeypatch.setattr(compose_ai, "get_image_provider", lambda _name: FakeProvider())
    monkeypatch.setattr(compose_ai, "_valid_image", lambda path: True)

    out = compose_ai._local_image("người que chạy", (1080, 1920), tmp_path)

    assert out.parent.name == "local_images"
    assert out.name == "3e6fcabdfd0c5a66.png"


def test_render_ai_giu_bat_bien_khong_mutate_voiceover(monkeypatch, tmp_path):
    # Arrange — chặn mọi I/O ngoài (stock + ffmpeg + concat)
    seg = Segment(caption="cap", narration="n", broll="x")
    vo = Voiceover(topic="t", title="T", description="d")
    object.__setattr__(vo, "segments", (seg,))  # voiceover gốc

    fake_bg = tmp_path / "bg.mp4"
    fake_bg.write_bytes(b"x")
    monkeypatch.setattr(compose_ai.slide, "_audio_duration", lambda a: 2.0)
    monkeypatch.setattr(compose_ai, "_moving_background",
                        lambda *a, **k: fake_bg)
    monkeypatch.setattr(compose_ai, "_broll_clip", lambda *a, **k: None)
    monkeypatch.setattr(compose_ai, "_broll_caption_clip", lambda *a, **k: None)
    monkeypatch.setattr(compose_ai, "_hook_coldopen", lambda *a, **k: None)
    monkeypatch.setattr(compose_ai.transitions, "concat_with_transitions",
                        lambda clips, flags, out, **k: None)
    monkeypatch.setattr(compose_ai, "_timeline_duration", lambda clips: 2.0)
    monkeypatch.setattr(compose_ai, "validate_render", lambda *a, **k: None)

    result = compose_ai.render_video_ai(vo)

    # Assert — trả RenderedVideo làm giàu, KHÔNG đổi bản gốc
    assert result.video_path is not None
    assert vo.segments[0].broll == "x"  # input nguyên vẹn


def test_beat_durations_giu_tong_va_cat_nhieu_canh():
    # Đoạn 24s, cadence thường ~6s -> 4 beat đều, tổng giữ nguyên
    durs = compose_ai._beat_durations(24.0, hook=False)
    assert len(durs) == 4
    assert abs(sum(durs) - 24.0) < 1e-6
    assert all(d <= compose_ai.BEAT_TARGET_SEC + 0.5 for d in durs)


def test_beat_durations_hook_cat_day_hon():
    # Cùng thời lượng, hook cắt nhiều beat hơn nhịp thường -> năng lượng cao
    normal = compose_ai._beat_durations(20.0, hook=False)
    hook = compose_ai._beat_durations(20.0, hook=True)
    assert len(hook) > len(normal)
    assert abs(sum(hook) - 20.0) < 1e-6


def test_beat_durations_doan_ngan_mot_beat():
    durs = compose_ai._beat_durations(2.0, hook=False)
    assert durs == [2.0]


def test_timeline_duration_tru_overlap_transition(monkeypatch, tmp_path):
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"]
    durations = {clips[0]: 10.0, clips[1]: 8.0, clips[2]: 7.0}
    monkeypatch.setattr(compose_ai.transitions, "_duration",
                        lambda path: durations[path])

    assert compose_ai._timeline_duration(clips, xfade=0.4) == pytest.approx(24.2)


def test_valid_clip_rejects_cached_segment_with_wrong_dimensions(monkeypatch, tmp_path):
    clip = tmp_path / "segment.mp4"
    clip.write_bytes(b"fake")

    class Result:
        stdout = "10.0\n"

    monkeypatch.setattr(compose_ai.subprocess, "run", lambda *a, **k: Result())
    monkeypatch.setattr(compose_ai, "_clip_dims", lambda path: (1920, 1080))

    assert compose_ai._valid_clip(
        clip,
        expected_duration=10.0,
        expected_dims=(1080, 1920),
    ) is False


def test_fetch_broll_variants_tra_nhieu_shot_khac_nhau(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "pexels_api_key", "k")
    monkeypatch.setattr(stock, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(stock, "_search_links",
                        lambda q, key, **k: ["a", "b", "c"])
    downloaded: list[str] = []
    monkeypatch.setattr(stock, "_download",
                        lambda url, dest: (downloaded.append(url), dest.write_bytes(b"x")))

    paths = stock.fetch_broll_variants("focus", 3)
    assert len(paths) == 3
    assert len(set(paths)) == 3  # mỗi shot một file cache riêng
    assert downloaded == ["a", "b", "c"]


def test_emphasis_windows_chia_deu_va_trong_thoi_luong():
    wins = compose_ai._emphasis_windows(2, 10.0)
    assert len(wins) == 2
    # mỗi cửa sổ nằm trong [0, duration] và không vượt quá nhau
    assert all(0 <= s < e <= 10.0 for s, e in wins)
    assert wins[0][1] <= wins[1][0]  # không chồng lấn


def test_emphasis_overlay_chip_upper_third_rgba():
    img = compose_ai._emphasis_overlay("Quy tắc 2 phút", dims=(1080, 1920))
    assert img.mode == "RGBA"
    assert img.size == (1080, 1920)


def test_hook_coldopen_none_khi_khong_co_segment_hook():
    seg = Segment(caption="c", narration="n", broll="x")  # hook=False mặc định
    vo = Voiceover(topic="t", title="T", description="d")
    object.__setattr__(vo, "segments", (seg,))
    assert compose_ai._hook_coldopen(
        vo, dims=(1080, 1920), landscape=False,
        work=__import__("pathlib").Path("/tmp"), slug="s", used=set()) is None


def test_broll_clip_ep_duration_theo_audio(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(compose_ai.slide, "_audio_duration", lambda audio: 12.345)
    monkeypatch.setattr(compose_ai.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))

    compose_ai._broll_clip(
        tmp_path / "bg.mp4",
        tmp_path / "overlay.png",
        tmp_path / "audio.mp3",
        tmp_path / "out.mp4",
        dims=(1080, 1920),
    )

    cmd = calls[0]
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "12.345"


def test_broll_caption_clip_ep_duration_theo_audio(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(compose_ai.slide, "_audio_duration", lambda audio: 7.89)
    monkeypatch.setattr(compose_ai.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))

    compose_ai._broll_caption_clip(
        tmp_path / "bg.mp4",
        tmp_path / "base.png",
        [(tmp_path / "word.png", 0.0, 1.0)],
        tmp_path / "audio.mp3",
        tmp_path / "out.mp4",
        dims=(1080, 1920),
    )

    cmd = calls[0]
    assert "-t" in cmd
    assert cmd[cmd.index("-t") + 1] == "7.890"


def test_fetch_broll_variants_dedup_xuyen_video(monkeypatch, tmp_path):
    # Bộ đếm `exclude` cấp-video: lần gọi sau ưu tiên link CHƯA dùng -> chống lặp clip
    monkeypatch.setattr(settings, "pexels_api_key", "k")
    monkeypatch.setattr(stock, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(stock, "_search_links",
                        lambda q, key, **k: ["a", "b", "c", "d"])
    monkeypatch.setattr(stock, "_download",
                        lambda url, dest, **k: dest.write_bytes(b"x"))

    used: set[str] = set()
    first = stock.fetch_broll_variants("focus", 2, exclude=used)
    second = stock.fetch_broll_variants("focus", 2, exclude=used)

    assert used == {"a", "b", "c", "d"}  # 4 link đều được dùng, không lặp
    assert set(first).isdisjoint(set(second))  # hai segment ra cảnh KHÁC nhau


def test_fetch_broll_variants_tai_dung_khi_het_link_moi(monkeypatch, tmp_path):
    # Hết link mới -> mới quay lại tái dùng link cũ (không crash, vẫn đủ count)
    monkeypatch.setattr(settings, "pexels_api_key", "k")
    monkeypatch.setattr(stock, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(stock, "_search_links", lambda q, key, **k: ["a", "b"])
    monkeypatch.setattr(stock, "_download",
                        lambda url, dest, **k: dest.write_bytes(b"x"))

    used: set[str] = set()
    paths = stock.fetch_broll_variants("focus", 3, exclude=used)  # xin 3 nhưng chỉ có 2
    assert len(paths) == 2  # tối đa số link sẵn có; caller round-robin


def test_loader_doc_emphasis_hook_transition(tmp_path):
    from ytb_pipeline.ideation.generator import load_script
    import json
    data = {
        "title": "T", "topic": "t", "description": "d",
        "compliance": {"passed": True},
        "sections": [
            {"narration": "x" * 1100, "caption": "cap", "broll": "gym",
             "emphasis": ["Quy tắc 2 phút"], "hook": True, "transition": True},
        ],
    }
    p = tmp_path / "x.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    script = load_script(p)
    seg = script.segments[0]
    assert seg.emphasis == ("Quy tắc 2 phút",)
    assert seg.hook is True
    assert seg.transition is True
