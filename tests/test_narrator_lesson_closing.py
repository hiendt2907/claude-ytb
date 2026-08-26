"""The approved new closing shape for `narrative_mode == "character_story"`:
1 narrator + 1 lead + 1 supporting character, ending on the NARRATOR
generalising the story into a lesson spoken directly to the viewer — instead
of the legacy contract, which requires the final beat to be a concrete
bounded action a CHARACTER does (`qa_agent._check_immediate_action`).

Root cause verified here, not assumed: the approved demo's ending ("Lần tới
khi X, hãy Y" said by the narrator, generalising rather than showing a
character do something measurable) fails `_check_immediate_action` today,
because that rule only accepts either an imperative viewer command
(`_IMMEDIATE_ACTION_HINTS`) or a bounded, character-shown action
(`_has_bounded_action`) — a narrator's abstract lesson satisfies neither.

The fix is a profile-declared `content_rules.narrator_lesson_closing: bool`
(default False) so existing character_story profiles that still want the
bounded-action ending keep passing unchanged, and only a profile that opts in
gets the new narrator-lesson-ending contract. Every fixture here is a
generic two-coworker profile, NOT `ban-so-6`, to prove the fix is
engine-level rather than tuned to one series/character names.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline.agents import qa_agent
from ytb_pipeline.config.settings import settings
from ytb_pipeline.content_profiles import load_content_profile

# A narrator line that generalises the story into a lesson, spoken directly
# to the viewer — the shape of the approved demo's closing. It contains no
# imperative viewer-command hint and no bounded/measurable character action,
# so today's rule must reject it.
NARRATOR_LESSON_ENDING = (
    "Đừng chờ đối phương lên tiếng trước. Câu hỏi bị bỏ lỡ hôm nay chính là "
    "câu trả lời người kia đang mong đợi."
)


def _payload(profile_id: str, *, narrator_lesson_closing: bool | None) -> dict:
    content_rules = {
        "require_pexels_query": False,
        "require_short_source_trace": False,
        "require_conversation_turns": True,
    }
    if narrator_lesson_closing is not None:
        content_rules["narrator_lesson_closing"] = narrator_lesson_closing
    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "version": "1.0.0",
        "display_name": profile_id,
        "topic": "Two coworkers working through an unspoken question",
        "narrative_mode": "character_story",
        "prompts": {"editorial": "prompts/editorial.md"},
        "formats": {
            "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 4},
            "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 10},
        },
        "providers": {
            "llm": "xkiro",
            "tts": "xkiro",
            "render": "story",
            "broll_strategy": "none",
            "broll_allow_downloads": False,
        },
        "voice_cast": {
            "narrator": "standard-female-vietnamese",
            "hieu": "confident-male-vietnamese",
            "lam": "sweet-female-vietnamese",
        },
        "content_rules": content_rules,
        "render": {
            "assets_dir": "assets",
            "show_captions": True,
            "inter_segment_gap_sec": 0.3,
            "transition_overlap_sec": 0.3,
        },
    }


def _write_profile(root: Path, profile_id: str, payload: dict) -> Path:
    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "prompts" / "editorial.md").write_text(
        f"Editorial rules for {profile_id}", encoding="utf-8"
    )
    (folder / "profile.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return folder


def _load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile_id: str, *, narrator_lesson_closing: bool | None):
    payload = _payload(profile_id, narrator_lesson_closing=narrator_lesson_closing)
    _write_profile(tmp_path, profile_id, payload)
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    return load_content_profile(profile_id, profiles_dir=tmp_path)


def _script(final_narration: str, *, profile_id: str, version: str, final_speaker: str = "narrator"):
    return SimpleNamespace(
        video_type="short",
        content_profile_id=profile_id,
        content_profile_version=version,
        segments=(
            SimpleNamespace(narration="Bảy giờ tối, Hiếu ngồi lại bàn làm việc.", speaker_id="narrator", payoff=""),
            SimpleNamespace(narration='"Sao cậu không hỏi thẳng chị ấy?"', speaker_id="lam", payoff=""),
            SimpleNamespace(narration=final_narration, speaker_id=final_speaker, payoff="hoc-duoc-cach-hoi-thang"),
        ),
    )


def test_narrator_lesson_ending_is_a_real_conflict_with_bounded_action_rule(tmp_path, monkeypatch):
    """RED (pre-fix expectation): a profile that does NOT declare the new
    field must keep the legacy bounded-action ending contract, so the
    narrator-lesson ending is still rejected. This is the regression half of
    the contract, proven with a real rule run — not assumed.
    """
    profile = _load(tmp_path, monkeypatch, "lesson-off-fixture", narrator_lesson_closing=None)

    script = _script(NARRATOR_LESSON_ENDING, profile_id=profile.profile_id, version=profile.version)

    violations = qa_agent._check_immediate_action(script)

    assert [v["rule"] for v in violations] == ["immediate_action"]


def test_narrator_lesson_ending_passes_when_profile_opts_in(tmp_path, monkeypatch):
    """GREEN: a profile that declares narrator_lesson_closing=true accepts a
    narrator line that generalises the story into a lesson for the viewer.
    """
    profile = _load(tmp_path, monkeypatch, "lesson-on-fixture", narrator_lesson_closing=True)

    script = _script(NARRATOR_LESSON_ENDING, profile_id=profile.profile_id, version=profile.version)

    violations = qa_agent._check_immediate_action(script)

    assert violations == []


def test_narrator_lesson_may_name_a_cast_member_only_in_its_next_episode_bridge(tmp_path, monkeypatch):
    """The lesson itself addresses viewers; its separate trailer may set up cast action."""
    profile = _load(tmp_path, monkeypatch, "lesson-bridge-fixture", narrator_lesson_closing=True)
    script = _script(
        "Khi bạn chờ chắc chắn trước khi hỏi, bạn sẽ chỉ kéo dài phần đoán. "
        "Tập sau, hieu sẽ đứng trước một lựa chọn khác: giữ im lặng hay nói rõ điều mình cần.",
        profile_id=profile.profile_id,
        version=profile.version,
    )

    assert qa_agent._check_immediate_action(script) == []


def test_narrator_lesson_ending_still_rejected_for_non_narrator_speaker(tmp_path, monkeypatch):
    """A character speaking an abstract lesson is not the approved shape —
    the lesson must come from the narrator, addressed to the viewer."""
    profile = _load(tmp_path, monkeypatch, "lesson-on-fixture-2", narrator_lesson_closing=True)

    script = _script(
        NARRATOR_LESSON_ENDING,
        profile_id=profile.profile_id,
        version=profile.version,
        final_speaker="hieu",
    )

    violations = qa_agent._check_immediate_action(script)

    assert [v["rule"] for v in violations] == ["immediate_action"]
