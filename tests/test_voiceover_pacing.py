"""Test nhịp ngắt nghỉ giọng đọc — chia narration thành cụm + khoảng lặng sau cụm."""

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
    assert profile.edge_rate.startswith("-")


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
