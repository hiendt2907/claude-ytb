"""Test nhịp ngắt nghỉ giọng đọc — chia narration thành cụm + khoảng lặng sau cụm."""

import pytest

from ytb_pipeline.voiceover import tts
from ytb_pipeline.pkg.models import Script, Segment


def test_split_pacing_sentence_gets_sentence_pause():
    # Arrange
    text = "Xin chào. Tạm biệt."

    # Act
    pieces = tts._split_for_pacing(text, comma_sec=0.25, sentence_sec=0.4)

    # Assert — cụm đầu kết bằng dấu chấm → nghỉ dài; cụm cuối nghỉ 0 (để mức segment lo)
    assert pieces[0] == ("Xin chào.", 0.4)
    assert pieces[-1][1] == 0.0


def test_split_pacing_comma_gets_shorter_pause():
    pieces = tts._split_for_pacing("Một, hai ba.", comma_sec=0.25, sentence_sec=0.4)
    assert pieces[0] == ("Một,", 0.25)


def test_split_pacing_empty_returns_empty():
    assert tts._split_for_pacing("", comma_sec=0.25, sentence_sec=0.4) == []


def test_split_pacing_single_clause_no_internal_pause():
    pieces = tts._split_for_pacing("Một câu không dấu", comma_sec=0.25, sentence_sec=0.4)
    assert pieces == [("Một câu không dấu", 0.0)]


def test_split_pacing_preserves_all_words():
    text = "Học nhanh, nhớ lâu. Hiệu quả thật!"
    pieces = tts._split_for_pacing(text, comma_sec=0.2, sentence_sec=0.5)
    joined = " ".join(p for p, _ in pieces)
    assert "Học nhanh" in joined and "nhớ lâu" in joined and "Hiệu quả thật" in joined


def test_voice_profile_entertainment_is_fast_and_not_news_reader():
    script = Script(
        topic="giải trí",
        title="Người Que Té Vì Cái Ghế",
        description="Kéo view bằng clip hài.",
        tags=("người que", "viral shorts"),
        segments=(Segment(caption="c", narration="Người que chạy rồi té cái rầm."),),
    )

    profile = tts._voice_profile(script)

    assert profile.name == "entertainment"
    assert profile.sentence_sec < tts.VOICE_NEUTRAL.sentence_sec
    assert profile.edge_rate.startswith("+")


def test_voice_profile_knowledge_is_slower_and_more_inspiring():
    script = Script(
        topic="kiến thức tâm lý",
        title="Một Cơ Chế Khiến Bạn Trì Hoãn",
        description="Video kiến thức giúp người xem ở lại lâu hơn.",
        tags=("tâm lý", "phát triển bản thân"),
        segments=(Segment(caption="c", narration="Đây là một cơ chế rất đáng chú ý."),),
    )

    profile = tts._voice_profile(script)

    assert profile.name == "knowledge"
    assert profile.sentence_sec > tts.VOICE_NEUTRAL.sentence_sec
    assert tts._edge_rate_pct(profile.edge_rate) < tts._edge_rate_pct(tts.VOICE_NEUTRAL.edge_rate)


def test_prepare_narration_removes_leaked_stage_directions():
    text = (
        "Cú hình tiếp theo: người que nhìn camera. "
        "Beat sau: cái ghế tự chạy mất. Chốt cảnh: người que đứng hình."
    )

    cleaned = tts._prepare_narration(text)

    assert "Cú hình tiếp theo" not in cleaned
    assert "Beat sau" not in cleaned
    assert "Chốt cảnh" not in cleaned
    assert "người que nhìn camera" in cleaned


def test_segment_performance_defaults_are_backward_compatible():
    seg = Segment(caption="c", narration="Một câu.")
    assert seg.voice_style == ""
    assert seg.voice_tempo is None
    assert seg.voice_pitch is None


def test_segment_profile_overrides_are_applied_to_profile():
    seg = Segment(
        caption="c", narration="Một câu.", voice_style="serious",
        voice_tempo=0.9, voice_pitch=-1.0, voice_gain=1.0,
        voice_pause_before=0.25, voice_pause_after=0.5,
    )
    profile = tts._segment_profile(seg, tts.VOICE_KNOWLEDGE)
    assert profile.name == "serious"
    assert profile.f5_tempo == 0.9
    assert profile.pitch_semitones == -1.0
    assert profile.gain_db == 1.0
    assert profile.pause_before == 0.25
    assert profile.pause_after == 0.5


def test_segment_profile_rejects_unsafe_overrides():
    seg = Segment(caption="c", narration="Một câu.", voice_tempo=2.0, voice_pitch=9.0)
    try:
        tts._segment_profile(seg, tts.VOICE_KNOWLEDGE)
    except ValueError as exc:
        assert "voice_tempo" in str(exc) or "voice_pitch" in str(exc)
    else:
        raise AssertionError("unsafe prosody override must fail fast")


def test_script_loader_reads_per_segment_voice_controls(tmp_path):
    from ytb_pipeline.ideation.generator import _segment_from_raw

    seg = _segment_from_raw({
        "narration": "Câu nói nghiêm túc.",
        "voice_style": "serious",
        "voice_tempo": 0.92,
        "voice_pitch": -1,
        "voice_gain": 1.0,
        "voice_pause_before": 0.3,
        "voice_pause_after": 0.4,
    }, "demo.json")
    assert seg.voice_style == "serious"
    assert seg.voice_tempo == 0.92
    assert seg.voice_pitch == -1.0
    assert seg.voice_pause_after == 0.4


def test_auto_profile_routes_segment_by_narrative_role():
    segments = (
        Segment(caption="c", narration="Bạn tưởng mọi người đều đang nhìn mình.", hook=True),
        Segment(caption="c", narration="Nhưng đây mới là phần đáng sợ.", danger=True),
        Segment(caption="c", narration="Trong tập tiếp theo, chúng ta sẽ xem cơ chế này.") ,
    )
    assert tts._segment_profile(segments[0], tts.VOICE_KNOWLEDGE, 0, 3).name == "hook"
    assert tts._segment_profile(segments[1], tts.VOICE_KNOWLEDGE, 1, 3).name == "serious"
    assert tts._segment_profile(segments[2], tts.VOICE_KNOWLEDGE, 2, 3).name == "conclusion"


def test_explicit_profile_wins_over_auto_routing():
    seg = Segment(caption="c", narration="Câu bình thường.", hook=True, voice_style="curious")
    assert tts._segment_profile(seg, tts.VOICE_KNOWLEDGE, 0, 1).name == "curious"


async def test_edge_tts_receives_profile_rate_and_pitch(monkeypatch, tmp_path):
    calls = []

    class FakeCommunicate:
        def __init__(self, text, voice, **kwargs):
            calls.append((text, voice, kwargs))

        async def save(self, path):
            tmp_path.joinpath("saved").write_text(path, encoding="utf-8")

    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)

    await tts._tts("Xin chào", "vi-VN-NamMinhNeural", tmp_path / "out.mp3", tts.VOICE_ENTERTAINMENT)

    assert calls[0][2]["rate"] == tts.VOICE_ENTERTAINMENT.edge_rate
    assert calls[0][2]["pitch"] == tts.VOICE_ENTERTAINMENT.edge_pitch


def test_to_mp3_applies_tempo_when_profile_needs_it(monkeypatch, tmp_path):
    calls = []
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.mp3"
    src.write_bytes(b"wav")

    class Result:
        returncode = 0

    monkeypatch.setattr(tts.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or Result())

    tts._to_mp3(src, dst, tempo=tts.VOICE_ENTERTAINMENT.f5_tempo)

    assert "-filter:a" in calls[0]
    assert any("atempo=" in part for part in calls[0])


def test_f5_tempo_matches_each_edge_profile_speed():
    for profile in tts.VOICE_PROFILES.values():
        edge_multiplier = 1 + tts._edge_rate_pct(profile.edge_rate) / 100
        assert profile.f5_tempo == pytest.approx(edge_multiplier)


def test_legacy_hook_copy_does_not_route_every_section_as_hook():
    from ytb_pipeline.ideation.generator import _segment_from_raw

    segment = _segment_from_raw({
        "narration": "Một đoạn giải thích bình thường.",
        "hook": "Mô tả câu hook để dựng hình.",
        "transition": "Mô tả chuyển cảnh.",
    }, "legacy.json")

    assert segment.hook is False
    assert segment.hook_text == "Mô tả câu hook để dựng hình."
    assert segment.transition is False
    assert segment.transition_text == "Mô tả chuyển cảnh."


def test_f5_segment_cache_key_includes_tempo(monkeypatch):
    from ytb_pipeline.voiceover.f5_provider import F5_INFERENCE_SPEED

    monkeypatch.setattr(tts.settings, "tts_provider", "f5")

    path = tts._segment_audio_path("demo", tts.VOICE_KNOWLEDGE, 0)

    assert f"f5x{tts.VOICE_KNOWLEDGE.f5_tempo:.2f}" in path.name
    assert f"s{F5_INFERENCE_SPEED:.2f}" in path.name


def test_to_mp3_trims_provider_boundary_silence(monkeypatch, tmp_path):
    calls = []
    src = tmp_path / "in.wav"
    dst = tmp_path / "out.mp3"
    src.write_bytes(b"wav")

    class Result:
        returncode = 0

    monkeypatch.setattr(tts.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd) or Result())

    tts._to_mp3(src, dst)

    filter_args = [part for part in calls[0] if isinstance(part, str) and "silenceremove=" in part]
    assert filter_args
    assert "stop_periods=1" in filter_args[0]


def test_synth_all_edge_parallel_giu_thu_tu_voi_nhieu_worker(monkeypatch, tmp_path):
    # Arrange — 6 segment, 4 worker song song, synth giả ghi file + đo giả
    monkeypatch.setattr(tts, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(tts.settings, "edge_tts_workers", 4)
    monkeypatch.setattr(
        tts, "_synth_segment",
        lambda text, voice, path, profile: path.write_bytes(b"x"),
    )
    monkeypatch.setattr(tts, "_probe_duration", lambda p: 1.5)
    script = Script(
        topic="t", title="Thu Tu Song Song", description="d", tags=(),
        segments=tuple(
            Segment(caption=f"c{i}", narration=f"n{i}") for i in range(6)
        ),
    )

    # Act
    voiced = tts._synth_all_edge_parallel(script, "slug", tts.VOICE_NEUTRAL)

    # Assert — thứ tự kết quả LUÔN khớp thứ tự segment gốc dù chạy đa luồng
    assert [s.narration for s in voiced] == [f"n{i}" for i in range(6)]
    assert all(s.duration_sec == 1.5 for s in voiced)
