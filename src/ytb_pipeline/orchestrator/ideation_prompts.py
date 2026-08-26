"""Prompt templates cho `ytb batch start` — tách khỏi ideation_cmd.py.

Prompt là versioned artifact (xem CLAUDE.md mục Prompt Standards): mọi thay đổi
prompt ở đây diff được qua git, không rải string trong logic gọi provider.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from ..analytics.quality_report import REQUIRED_PURPOSES_BY_VIDEO_TYPE
from ..config.settings import settings
from ..content_contract import (
    CONTRACT_VERSION,
    chars_per_min_for_provider,
    contract_for,
    effective_chars_per_min,
)
from ..content_profiles import (
    ContentProfileError,
    LEGACY_SHORT_EXPANSION_PURPOSES,
    load_content_profile,
)
from ..ideation.generation_schema import SECTION_PURPOSES

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile

SHORT_CONTRACT = contract_for("short")
LONG_CONTRACT = contract_for("long")
LONG_MIN_MINUTES = int(LONG_CONTRACT.viewer_runtime_bounds_sec[0] / 60)
LONG_MAX_MINUTES = int(LONG_CONTRACT.viewer_runtime_bounds_sec[1] / 60)
SHORT_MIN_MINUTES = SHORT_CONTRACT.viewer_runtime_bounds_sec[0] / 60
SHORT_MAX_MINUTES = SHORT_CONTRACT.viewer_runtime_bounds_sec[1] / 60
SHORT_ANSWER_START_TARGET_SEC = SHORT_CONTRACT.answer_start_target_sec or 4.0

# Ideation and loader must plan with the same active TTS profile.  F5 is the
# production default, while Edge remains a valid deterministic development path.
PLANNING_CHARS_PER_MIN = chars_per_min_for_provider(settings.tts_provider, video_type="short")
# A Long is one continuous read and runs faster than a Short of the same
# character count, so its budget must be planned at its own measured rate.
LONG_PLANNING_CHARS_PER_MIN = chars_per_min_for_provider(
    settings.tts_provider, video_type="long",
)
# Derived from the active TTS rate, never a fixed literal: the same character
# count starts the answer at a different second on each provider.
SHORT_SITUATION_MAX_CHARS = SHORT_CONTRACT.situation_char_budget(
    chars_per_minute=PLANNING_CHARS_PER_MIN,
)
SHORT_MIN_CHARS, SHORT_MAX_CHARS = SHORT_CONTRACT.audio_runtime_bounds_sec(
    segment_count=SHORT_CONTRACT.minimum_sections
)
SHORT_MIN_CHARS = int(PLANNING_CHARS_PER_MIN * SHORT_MIN_CHARS / 60)
SHORT_MAX_CHARS = int(PLANNING_CHARS_PER_MIN * SHORT_MAX_CHARS / 60)
SHORT_SAFE_MIN_CHARS, SHORT_SAFE_MAX_CHARS = SHORT_CONTRACT.safe_character_bounds(
    chars_per_minute=PLANNING_CHARS_PER_MIN, segment_count=SHORT_CONTRACT.minimum_sections
)
# Where `normalize_short_narration` aims when it has to trim an overlong Short.
# This used to be `PLANNING_CHARS_PER_MIN * 1.25` — the midpoint of the old
# 60-90s window written as a literal.  Once the window moved to 30-45s that
# literal (1,287 chars) sat ABOVE SHORT_MAX_CHARS (793), so the trimmer computed
# a growth ratio, left every section untouched, and still reported success; the
# script then failed the runtime gate after ideation had already been paid for.
# Deriving the midpoint from the active safe band keeps the same intent at any
# window and can never exceed the cap it is supposed to enforce.
SHORT_TARGET_CHARS = (SHORT_SAFE_MIN_CHARS + SHORT_SAFE_MAX_CHARS) // 2
# Per-section prompt budgets, derived instead of tabulated.  The prompt used to
# name a fixed six-section table (evidence 550-700, example 550-700, ...) whose
# sum was roughly three times the 30-45s budget, so the model could not satisfy
# the total and the table at once and reliably overshot.  Deriving the shares
# keeps the same editorial shape at any window.
SHORT_PROMPT_SECTIONS = SHORT_CONTRACT.minimum_sections
# Named from the release gate itself: the prompt used to list an editorial
# order (…, evidence, application, payoff) that a minimum-length Short could
# satisfy while dropping a purpose the gate requires.
SHORT_REQUIRED_PURPOSES = ", ".join(REQUIRED_PURPOSES_BY_VIDEO_TYPE["short"])
SHORT_PAYOFF_MAX_CHARS = int(SHORT_SAFE_MAX_CHARS * 0.20)
SHORT_BODY_SECTION_CHARS = max(
    80,
    (SHORT_SAFE_MAX_CHARS - SHORT_SITUATION_MAX_CHARS - SHORT_PAYOFF_MAX_CHARS)
    // max(1, SHORT_PROMPT_SECTIONS - 2),
)
LONG_MIN_CHARS, LONG_MAX_CHARS = LONG_CONTRACT.audio_runtime_bounds_sec(
    segment_count=LONG_CONTRACT.minimum_sections
)
LONG_MIN_CHARS = int(LONG_PLANNING_CHARS_PER_MIN * LONG_MIN_CHARS / 60)
LONG_MAX_CHARS = int(LONG_PLANNING_CHARS_PER_MIN * LONG_MAX_CHARS / 60)
LONG_SAFE_MIN_CHARS, LONG_SAFE_MAX_CHARS = LONG_CONTRACT.safe_character_bounds(
    chars_per_minute=LONG_PLANNING_CHARS_PER_MIN, segment_count=LONG_CONTRACT.minimum_sections
)

CHANNEL_EDITORIAL_BRIEF = """Kênh là "1 Cốc Café 6h", theo ngách "phát triển bản thân THẬT, không self-help": giải thích một cơ chế tâm lý, hành vi hoặc mental model trong mỗi tập bằng tình huống đời thường cụ thể. Khán giả phải hiểu vì sao hành vi xảy ra, giới hạn của cơ chế và một bước áp dụng ít rào cản; không dùng khẩu hiệu, mẹo chữa nhanh hoặc lời hứa tuyệt đối. Short là phễu cho long-form cùng cơ chế, không phải clip độc lập chỉ để lấy view."""

SECTION_PURPOSES_LIST = ", ".join(SECTION_PURPOSES)

# Sourced from `agents/qa_agent.py::_check_story_hook` — that gate requires an
# ANCHOR (a concrete moment: a clock time, a place, a named cast member, an
# event already in progress) plus a STAKE (an unfinished obligation, deadline,
# consequence, or risk) in the opening narration, for every profile whose
# narrative_mode is "character_story". Before this constant existed, no
# generation or repair prompt stated that contract, so a model could pass
# every other gate and still fail QA's hook rule with no instruction telling
# it why. Never mention a specific series, cast name, or fixed example scene
# here — a new character_story profile must satisfy this from the rule alone.
STORY_HOOK_CONTRACT = (
    "The opening narration must pass a hook gate: it needs BOTH an anchor and "
    "a stake, or it is rejected. Anchor: name a concrete moment already in "
    "progress — a clock time, a specific place, or a named cast member — never "
    "a vague general time like \"mornings\" or \"lately\". Stake: state an "
    "unfinished obligation, a deadline, a consequence, or something the "
    "character could still lose, in that same opening — an anchor with no "
    "stake (a character just sitting somewhere) still fails this gate. Close "
    "the opening with an action or question that follows directly from that "
    "situation, not a separate topic."
)


# Sourced from `agents/qa_agent.py::_check_immediate_action` /
# `_is_narrator_lesson_closing` — the profile-declared
# `content_rules.narrator_lesson_closing` switches which ending contract that
# gate enforces. Never mention a specific series, cast name, or fixed episode
# here — this must hold for any character_story profile from the rule alone.
_BOUNDED_ACTION_CLOSING = (
    "End the final section on a concrete bounded action a viewer could "
    "copy — name a real quantity such as twenty minutes, three lines, "
    "one page — shown through what a character actually does."
)


def _character_story_closing_instruction(content_profile: "ContentProfile | None") -> str:
    if content_profile is not None and content_profile.content_rules.narrator_lesson_closing:
        narrator_id = content_profile.editorial_contract.narration_speaker_id
        instruction = (
            f"End on a section whose speaker_id is \"{narrator_id}\": the narrator "
            "generalises what just happened into a lesson spoken directly to the "
            "viewer (2-3 sentences, addressed to \"you\"/\"bạn\", not to a character) "
            "— state the principle the story demonstrated, not a command to act "
            "right now and not another character's dialogue."
        )
        if content_profile.content_rules.require_next_episode_bridge:
            instruction += (
                " In that same closing, naturally name the unresolved question or "
                "choice the next episode will examine; use a clear next-episode bridge "
                "such as 'Tập sau…', 'Lần tới…', or 'Hẹn gặp lại ở tập sau…'."
            )
        return instruction
    instruction = _BOUNDED_ACTION_CLOSING
    if content_profile is not None and content_profile.content_rules.require_next_episode_bridge:
        instruction += (
            " In the same natural closing, name the unresolved question or choice the next "
            "episode will examine; use a clear next-episode bridge such as 'Tập sau…', "
            "'Lần tới…', or 'Hẹn gặp lại ở tập sau…'."
        )
    return instruction


def _story_series_role_instruction(content_profile: "ContentProfile") -> str:
    """Return the profile-declared three-role story contract, if enabled."""
    rules = content_profile.content_rules
    if not rules.story_primary_speaker_id:
        return ""
    narrator_id = content_profile.editorial_contract.narration_speaker_id
    return (
        "This Long has exactly three speaking roles: narrator speaker_id is "
        f"\"{narrator_id}\"; primary speaker_id is \"{rules.story_primary_speaker_id}\"; "
        f"supporting speaker_id is \"{rules.story_supporting_speaker_id}\". "
        "The narrator owns the opening context/stakes and the final meaning; the primary "
        "character carries the choice under pressure; the supporting character listens, "
        "questions, or offers a specific counterpoint. Both characters must speak in the "
        "episode. Do not add a fourth speaker or turn the narrator into a second main character."
    )


def _hook_repair_directive(content_profile: "ContentProfile | None") -> str:
    """The contract text used to fix a QA `rule=hook` violation.

    Routed identically everywhere a hook repair can happen (the free-standing
    `repair_prompt` and the bounded `hook_repair_prompt` below): a
    character_story profile gets the same anchor+stake contract
    `qa_agent.py::_check_story_hook` enforces. Explainers then follow their
    declared Long opening mode, so a pain-first profile is never repaired into
    a legacy channel greeting.
    """
    if content_profile is not None and content_profile.narrative_mode == "character_story":
        return STORY_HOOK_CONTRACT
    if (
        content_profile is not None
        and content_profile.content_rules.long_opening_mode == "pain_first"
    ):
        return (
            "for a pain-first Long, keep the opening as a concrete observable pain scene "
            "and do not add a greeting or title read. In its first 28 spoken words, make "
            "the cost, contradiction, or question explicit with a concrete question or one "
            "tension marker (nhưng, thật ra, đừng, không phải, vì sao, sai lầm)."
        )
    return (
        "for a Long, keep the required greeting but make the first 28 spoken words "
        "after it contain a concrete question or one explicit tension marker "
        "(nhưng, thật ra, đừng, không phải, vì sao, sai lầm). Do not merely add a "
        "marker later in the section."
    )


def _long_opening_instruction(content_profile: "ContentProfile") -> str:
    """Return the one Long opening contract shared by generation and repair.

    The profile data, not `narrative_mode` nor profile id, decides whether an
    episode retains the historical greeting. This keeps new editorial formats
    compatible with the same workflow engine.
    """
    mode = content_profile.content_rules.long_opening_mode
    if mode == "pain_first":
        return (
            "OPENING MODE: PAIN_FIRST. For a Long, open immediately with one concrete, "
            "observable audience pain and the cost or pressure around it. Do not greet, "
            "read the title, or define the topic before that scene."
        )
    if mode == "story_context":
        return (
            "OPENING MODE: STORY_CONTEXT. For a Long, let the narrator open with a concrete "
            "scene, anchor, and stake required by the story contract. Do not force a channel greeting."
        )
    return (
        "OPENING MODE: CHANNEL_GREETING. For a Long, begin exactly with \"Mến chào các bạn,\" "
        "then the title and a topic-specific hook. In the first 28 spoken words after the "
        "greeting, include a concrete question or one explicit tension marker."
    )


def _long_closing_instruction(content_profile: "ContentProfile") -> str:
    """State the final beat expected by the profile's narrative form.

    This is deliberately a prompt contract, paired with the existing QA gates:
    explainers end on the viewer's immediate action; a story ends through its
    narrator's lesson and bridge. Neither format gets a detached promotional
    epilogue after its real ending.
    """
    if content_profile.narrative_mode == "character_story":
        return _character_story_closing_instruction(content_profile)
    if content_profile.narrative_mode == "mechanism_explainer":
        return (
            "CLOSING MODE: FINAL_ACTION. The final spoken section must contain one direct, "
            "specific action the viewer can do today, beginning with exactly \"Hãy \". Do not "
            "append a separate trailer, next-video promotion, or generic CTA after that action."
        )
    return ""


def _short_ending_instruction(content_profile: "ContentProfile") -> str:
    """Describe the Short's ending without coupling the engine to a channel.

    A funnel Short intentionally leaves the substantive answer for its declared
    Long.  A standalone explainer Short instead closes on an immediate action.
    The profile decides which outcome is editorially honest; QA verifies the
    corresponding observable contract.
    """
    if content_profile.content_rules.short_ending_mode == "funnel_bridge":
        return (
            "SHORT ENDING MODE: FUNNEL_BRIDGE. The final spoken section must naturally name "
            "what the declared Long will explain next and invite the viewer to continue there. "
            "Keep long_form_slug, cta_target, and source_long_slug identical. Do not replace "
            "that bridge with a generic imperative or pretend this Short has resolved the topic."
        )
    if content_profile.narrative_mode == "mechanism_explainer":
        return (
            "SHORT ENDING MODE: FINAL_ACTION. The final spoken section must contain one direct, "
            "specific action the viewer can do immediately."
        )
    return ""


def hook_repair_prompt(
    payload: dict, detail: str, *, content_profile: "ContentProfile | None" = None,
) -> str:
    """Ask for a bounded rewrite of ONLY the opening section's spoken text.

    Mirrors the shape of `short_expansion_prompt`/`long_extension_prompt`: one
    small JSON delta, every other field (title, section count, purposes,
    strategy, continuity, payoff/CTA) explicitly untouched, so a hook fix can
    never become an uncontrolled full-script rewrite.
    """
    context = {key: payload.get(key) for key in ("slug", "topic", "title", "video_type")}
    sections = payload.get("sections") or []
    context["first_section"] = sections[0] if sections else None
    directive = _hook_repair_directive(content_profile)
    return (
        "Rewrite ONLY the opening narration of this Vietnamese YouTube script to fix "
        "a QA hook rejection.\n"
        f"QA detail: {detail}\n"
        f"{directive}\n"
        'Return ONLY one JSON object shaped {"voiceover": <new Vietnamese opening '
        "text>}. Do not return the full script, markdown, or any other field. Keep "
        "the same speaker, purpose, and scene as the existing opening; do not "
        "introduce a new character, mechanism, event, or topic. Keep it natural to "
        "speak aloud — no stage directions, no camera language.\n\n"
        f"Script context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


STRATEGY_V1_CONTRACT = f"""Every newly generated Short MUST include a strategy object. strategy contains format_id, core_mechanism, audience_problem, angle, long_form_slug, playlist, cta_target, and hook. hook contains situation, core_answer, open_loop, answer_by_sec. Use format_id="core_answer_first_v1" unless explicit analytics feedback says another tested format won. The Short must show the situation in the first segment, put the exact core_answer in a section whose purpose is "core_answer", and set answer_by_sec to 5 or less. Every section must include purpose, one of exactly: {SECTION_PURPOSES_LIST}. Do not delay the core answer with a greeting, a generic question, or an abstract definition. The core_answer should be a careful explanation, not an absolute diagnosis or a dopamine cliché."""

PERSONAL_FINANCE_PSYCHOLOGY_PROFILE = "personal_finance_psychology"
_PERSONAL_FINANCE_MARKERS = ("tài chính", "tài chánh", "tiền bạc", "personal finance")


def is_personal_finance_psychology_request(requirement: str) -> bool:
    """Whether a batch must use the evidence-register safety contract."""
    normalized = requirement.casefold()
    # A scope exclusion ("không tư vấn tài chính") must not accidentally
    # turn an unrelated psychology topic into a finance-evidence task.  Strip
    # only the negated noun phrase; a real finance request elsewhere remains.
    normalized = re.sub(
        r"\b(?:không|khong|tránh|tranh)\b[^.;,\n]{0,32}?"
        r"\b(?:tài chính|tài chánh|tiền bạc|personal finance)\b",
        "",
        normalized,
    )
    return any(marker in normalized for marker in _PERSONAL_FINANCE_MARKERS)


def personal_finance_source_contract(requirement: str) -> str:
    """Return the mandatory source contract only for financial-behaviour batches."""
    if not is_personal_finance_psychology_request(requirement):
        return ""
    return f"""
Financial editorial profile is mandatory: set `editorial_profile` to
`{PERSONAL_FINANCE_PSYCHOLOGY_PROFILE}`. This is educational personal-finance
psychology, never investment, tax, legal, credit, insurance, or product advice.
Before writing, research the claim and retain only claims you can substantiate.
Return an `evidence_register` array. Each factual, numerical, financial, legal,
or research claim used in narration must have one row with: `claim`,
`source_title`, `publisher`, `published_year`, `url`, and `source_type`.
`source_type` is exactly `primary`, `peer_reviewed`, or `official`; every URL
must be a direct HTTPS source. Use a primary, peer-reviewed, or official source
where available. Never cite a search-result page, an unverifiable blog, another
creator, a made-up author, or a source you did not actually check. If a claim
cannot be entered in this register, remove it from the narration. In
`compliance.accuracy`, explicitly state that the evidence_register covers every
factual claim. `compliance.passed` is false until this register is complete.
"""

# System contract dùng chung cho lần sinh đầu và mọi vòng repair. Giữ ở đây để
# prompt là artifact có version/diff, không phân tán thành câu lệnh ngắn trong
# các call-site provider.
SCRIPT_GENERATION_SYSTEM_PROMPT = f"""You are the senior editorial writer and factual-safety reviewer for a Vietnamese YouTube channel.
Return exactly one valid JSON object and no markdown. Treat the user requirement and the declared JSON title/topic as the editorial contract.
Timing estimates use the active TTS provider's calibrated Vietnamese narration rate; measured audio is the final authority.

Non-negotiable editorial rules:
1. Set root JSON field `ruleset_id` to EXACTLY `{CONTRACT_VERSION}`. Every spoken sentence must directly serve the declared title and topic. Keep one coherent causal mechanism per video. Never import an example, mechanism, scene, CTA, or conclusion from another topic. Describe it naturally in Vietnamese; do not contort normal wording to satisfy a removed phrase-scanner.
2. For a Short without target_minutes, narration must be {SHORT_MIN_CHARS}-{SHORT_MAX_CHARS} Vietnamese characters for {SHORT_MIN_MINUTES:.2f}-{SHORT_MAX_MINUTES:.2f} minutes. Aim for {SHORT_SAFE_MIN_CHARS:,}-{SHORT_SAFE_MAX_CHARS:,} characters IN TOTAL; this total outranks every per-section number below. Use at least {SHORT_PROMPT_SECTIONS} sections and they MUST cover every required purpose, in this order: {SHORT_REQUIRED_PURPOSES}. A Short is REJECTED if any of them is missing, so spend the budget on those first and add an `evidence` section or a concrete example ONLY if the total still allows it. Keep situation ≤{SHORT_SITUATION_MAX_CHARS} characters and payoff/CTA ≤{SHORT_PAYOFF_MAX_CHARS} characters; split what remains among the middle sections, roughly {SHORT_BODY_SECTION_CHARS} characters each. Silently count the combined voiceover before responding and expand one middle section — never the hook — if under {SHORT_SAFE_MIN_CHARS:,}. For strategy-v1, the first `situation` is visual setup only, must include a concrete tension marker, and the `core_answer` must be section two. Its very first sentence must exactly equal hook.core_answer. `answer_by_sec` means when that sentence STARTS, not when the explanatory section ends. Keep the situation short enough that the answer is estimated to begin by {SHORT_ANSWER_START_TARGET_SEC:.0f}s, leaving safety before the hard 5s gate.
3. For a Long, set target_minutes to EXACTLY {LONG_MIN_MINUTES} and write {LONG_SAFE_MIN_CHARS:,}-{LONG_SAFE_MAX_CHARS:,} Vietnamese characters, within the validator's absolute {LONG_MIN_CHARS}-{LONG_MAX_CHARS} character range for a {LONG_MIN_MINUTES}-{LONG_MAX_MINUTES} minute Long. The pipeline measures planning duration as total_characters / {LONG_PLANNING_CHARS_PER_MIN:.0f} and verifies the actual audio stays {LONG_MIN_MINUTES}-{LONG_MAX_MINUTES} minutes. Build depth from the same mechanism: causal explanation, supported evidence, exact-topic example, application, and next-episode bridge; never stretch runtime with repeated phrasing. A Long may use richer section purposes than a Short, but it MUST still contain at least one section of each purpose the release gate requires: situation, core_answer, evidence, application, payoff. Open with a `situation` section that sets the concrete scene, and state the mechanism plainly in a `core_answer` section early — do not bury it.
4. Open a Short with a concrete conflict, consequence, or question; do not greet or read the title. Open a Long with "Mến chào các bạn," then its title and a topic-specific hook. In the first 28 spoken words after the greeting, the hook MUST contain either a concrete question or one explicit tension marker: "nhưng", "thật ra", "đừng", "không phải", "vì sao", or "sai lầm". Each section must add information, explain why, and use visuals that match its spoken narration. For EVERY section, `time_goal` is required and MUST be a positive JSON number in minutes (never 0/null/string/timestamp/range); use values such as 0.5, 0.75, or 1.0. Section time_goal values must sum approximately to the declared target duration. Use one optional retention beat in both Shorts and Longs: choose its natural position after the viewer has received a concrete insight (for a Short, usually the final third; for a Long, usually after an explanatory or application payoff). It should briefly state the specific value the viewer has just received and invite a lightweight next action such as liking or following/subscribing. Make it value-first, topic-specific, and conversational; do not use a fixed sentence, put it in every section, or interrupt the hook/explanation. The final narration section of BOTH Shorts and Longs must include: (a) one direct, specific action the viewer can do immediately, starting that sentence with exactly "Hãy " and naming the object, action, and a concrete time or scope; (b) a natural, brief invitation to like the video; and (c) a natural, brief invitation to subscribe to the channel for future videos. These like-and-subscribe invitations are a channel-growth requirement, not optional filler, and must fit the topic and tone without sounding repetitive or manipulative. For a Short with a funnel target, the long-form bridge CTA must remain present alongside the like and subscribe invitations. A question inviting a comment may follow, but never replace the action or the like-and-subscribe invitations.
5. Write knowledge, not slogans: explain the mechanism when it genuinely helps, use a concrete example that belongs to this exact topic, and give an immediately usable application. Keep those elements explicit in the narration, but choose natural wording; do not rely on fixed labels or template phrases. Do not drift into generic self-help, comedy, or unrelated advice. Channel topic compass: {CHANNEL_EDITORIAL_BRIEF}
6. Verify every factual, numerical, medical, financial, legal, or research claim before including it. Omit any claim whose source cannot be named in the compliance notes; never invent statistics, studies, authors, or certainty.
   When the request is personal-finance psychology, follow its evidence-register contract exactly; a plausible-sounding citation is still a failure.
7. Respect YouTube community safety, copyright, advertiser-friendliness, COPPA, and the existing-ledger blacklist supplied in the user prompt. Use original narration and license-safe B-roll instructions.
8. When video_type is "short", strategy-v1 is mandatory: {STRATEGY_V1_CONTRACT} The JSON must contain this strategy object before sections; a missing or incomplete strategy is invalid output, never a legacy fallback.
9. Every new script MUST include a `thumbnail_brief` JSON object with exactly these non-empty string fields: `visual_contradiction`, `subject`, `emotion`, and `headline`. Show one instantly understandable visual contradiction, a concrete human/object subject, and one emotion; `headline` must be 4 words or fewer. The headline must reinforce the title/hook rather than repeat the full title. Produce this brief in the first JSON response; do not wait for a separate thumbnail or repair prompt.

Before responding, silently audit title/topic-to-narration coherence sentence by sentence, the character contract, factual support, one mechanism, visual alignment, and the required JSON schema. If any check fails, rewrite the script before returning it."""


def script_generation_system_prompt(
    content_profile: "ContentProfile | None" = None,
    *,
    video_type: str | None = None,
) -> str:
    """Build a profile-scoped system contract without changing pipeline code.

    The historical constant remains the compatibility path for callers that do
    not yet declare a profile. New batch generation always supplies one.
    """
    if content_profile is None:
        return SCRIPT_GENERATION_SYSTEM_PROMPT
    requested_type = (video_type or "").strip().lower()
    if requested_type and requested_type not in {"short", "long"}:
        raise ContentProfileError(f"video_type không hợp lệ: {video_type!r}.")
    if requested_type and not content_profile.supports_generation(requested_type):
        raise ContentProfileError(
            f"Profile '{content_profile.profile_id}' không cho sinh {requested_type} mới."
        )
    active_types = (
        (requested_type,)
        if requested_type
        else tuple(kind for kind in ("short", "long") if content_profile.supports_generation(kind))
    )
    if not active_types:
        raise ContentProfileError(f"Profile '{content_profile.profile_id}' không có format nào được phép sinh.")
    format_prompt_names = set(content_profile.format_prompts.values())
    prompt_rules = "\n\n".join(
        content_profile.prompt_text(name)
        for name in content_profile.prompts
        if name not in format_prompt_names
    )
    format_structure = "\n\n".join(
        f"{kind.upper()} transcript structure:\n{content_profile.format_prompt_text(kind)}"
        for kind in active_types
        if content_profile.format_prompt_text(kind)
    )
    format_lines: list[str] = []
    purpose_rules: list[str] = []
    purpose_policy = content_profile.editorial_contract.purpose_policy
    purpose_vocabulary = ", ".join(purpose_policy.vocabulary)
    for kind in active_types:
        profile_format = content_profile.format_for(kind)
        format_contract = contract_for(kind, content_profile)
        rate = effective_chars_per_min(
            content_profile.providers.tts, video_type=kind, content_profile=content_profile,
        )
        chars = format_contract.safe_character_bounds(
            chars_per_minute=rate, segment_count=profile_format.min_sections
        )
        label = "Short" if kind == "short" else "Long"
        runtime = (
            f"{profile_format.viewer_min_sec:g}-{profile_format.viewer_max_sec:g}s"
            if kind == "short"
            else f"{profile_format.viewer_min_sec / 60:g}-{profile_format.viewer_max_sec / 60:g} minutes"
        )
        format_lines.append(
            f"- {label}: {runtime}, {profile_format.min_sections}-{profile_format.max_sections} "
            f"sections, aim for {chars[0]}-{chars[1]} Vietnamese narration characters."
        )
        required = ", ".join(purpose_policy.required_for(kind)) or "(none declared)"
        purpose_rules.append(f"- Required purposes for this {label}: {required}.")
    required_purposes_rule = (
        "\n".join(purpose_rules)
        + f"\n- Use only purposes from this profile's vocabulary: {purpose_vocabulary}."
    )
    if (
        content_profile.narrative_mode == "character_story"
        and "long" in active_types
        and "evidence" in purpose_policy.required_for("long")
    ):
        required_purposes_rule += (
            " In a character story, evidence may be a concrete observed consequence, response, "
            "or detail that tests the character's belief; do not invent a research claim just to "
            "fill this beat."
        )
    vg = content_profile.visual_generation
    story_long_contract = ""
    if (
        content_profile.narrative_mode == "character_story"
        and (
            requested_type == "long"
            or (not requested_type and active_types == ("long",))
        )
    ):
        story_long_contract = (
            f" {_story_series_role_instruction(content_profile)}"
            f" {_character_story_closing_instruction(content_profile)}"
        )
    if content_profile.narrative_mode == "character_story":
        narrator_id = content_profile.editorial_contract.narration_speaker_id
        visual_field_rule = (
            "Every section must include speaker_id and scene_characters (array of "
            f"cast ids visible in frame, from {sorted(n for n in content_profile.voice_cast if n != narrator_id)}, "
            "at most 2, [] for an establishing/prop shot with nobody visible — never "
            "invent visual_asset)."
            if vg is not None and vg.enabled
            else "Every section must include speaker_id and visual_asset."
        )
        narrative_contract = (
            f"{visual_field_rule} Dialogue must react to the previous line and sound "
            "natural when spoken. For a section whose speaker_id is a character, "
            "voiceover is exactly that character's spoken utterance: never narrate "
            "their action in third person and never put another character's reply "
            "inside it. Put action in a narrator section or visual_intent, and split "
            "a back-and-forth into separate speaker turns. Do not require strategy "
            "or Pexels fields. "
            + (
                "Every section must include turn. Narrator sections set turn=null. "
                "A character section sets turn to an object with non-empty scene and intent, "
                "and responds_to as null or a previous one-based section number it answers. "
                "turn is planning metadata only and must never appear in voiceover."
                if content_profile.content_rules.require_conversation_turns else ""
            )
            + story_long_contract
            + f" {STORY_HOOK_CONTRACT}"
        )
    else:
        strategy_rule = (
            f"For Shorts, strategy-v1 is mandatory: {STRATEGY_V1_CONTRACT}"
            if content_profile.content_rules.require_short_source_trace
            else "Do not require a strategy object unless the profile editorial contract above asks for one."
        )
        pexels_rule = (
            "Every section must include a grounded pexels_query for real stock footage."
            if content_profile.content_rules.require_pexels_query
            else "Do not require pexels_query unless the profile editorial contract above asks for it."
        )
        narrative_contract = f"{strategy_rule} {pexels_rule}"
    opening_contract = (
        _long_opening_instruction(content_profile) if "long" in active_types else ""
    )
    closing_contract = (
        _long_closing_instruction(content_profile) if "long" in active_types else ""
    )
    short_ending_contract = (
        _short_ending_instruction(content_profile) if "short" in active_types else ""
    )
    format_contract_lines = "\n".join(format_lines)
    return f"""You are the senior editorial writer for content profile
`{content_profile.profile_id}` version `{content_profile.version}`.
Return exactly one valid JSON object and no markdown. Set ruleset_id to
`{CONTRACT_VERSION}`, profile_id to `{content_profile.profile_id}`, and
profile_version to `{content_profile.version}`.

Profile editorial contract:
{prompt_rules}

Format contract:
{format_contract_lines}
- Every section needs a positive numeric time_goal, purpose, voiceover, and visual_intent.
{required_purposes_rule}

Format-specific transcript structure:
{format_structure or '(No extra structure file declared; follow the profile editorial contract.)'}

Narrative contract:
{narrative_contract}
{opening_contract}
{closing_contract}
{short_ending_contract}

Use original, safe, advertiser-friendly Vietnamese. Verify or omit factual
claims. Include a complete thumbnail_brief and compliance object. Silently
audit semantic continuity, spoken naturalness, timing, and JSON schema before
responding."""


def build_resume_prompt(remaining: int, type_of_vid: str, type_of_rules: str, existing_slugs: list[str]) -> str:
    """Prompt resume — nói rõ đã có bao nhiêu, cần thêm bao nhiêu, KHÔNG viết lại cũ."""
    vid_label = "Video dài (ngang, 12-15 phút)" if type_of_vid == "long" else "Short (dọc, 1-1.5 phút)"
    topic_guidance = (
        "TỰ chọn chủ đề hợp ngách kênh (đọc memory dự án + ledger)."
        if type_of_rules == "auto"
        else (
            f"Ý tưởng người dùng đưa là RÀNG BUỘC CHÍNH: {type_of_rules}. "
            "Được chia thành nhiều góc nhìn khác nhau nhưng không được đổi sang chủ đề khác."
        )
    )
    slugs_str = "\n".join(f"  - {s}" for s in existing_slugs)
    return (
        f"RESUME IDEATION — tiếp tục batch bị dừng giữa chừng.\n\n"
        f"Các slug SAU ĐÂY đã có script + đã đăng ký trong auto_state.json, "
        f"TUYỆT ĐỐI KHÔNG viết lại hay đăng ký lại:\n{slugs_str}\n\n"
        f"Cần viết THÊM {remaining} video loại \"{vid_label}\" — dùng skill youtube-ideation, "
        f"tuân thủ ĐẦY ĐỦ .claude/skills/youtube-ideation/video-quality-rules.md "
        f"(cổng verify mục 0, luật series mục 0d, độ dài mục 2a/2b). {topic_guidance}\n\n"
        f"La bàn chủ đề bắt buộc:\n{CHANNEL_EDITORIAL_BRIEF}\n\n"
        "Every section MUST include time_goal as a positive JSON number of minutes; never 0/null/string/timestamp/range (examples: 0.5, 0.75, 1.0). The sum of time_goal values must approximately match the target duration.\n\n"
        "Trước khi chọn chủ đề: đọc data/ledger.md, loại bỏ mọi chủ đề trùng/tương tự "
        "(mọi status, không chỉ done).\n\n"
        "QUY TRÌNH BẮT BUỘC — làm TUẦN TỰ từng video, KHÔNG làm batch:\n"
        "  1. Chọn chủ đề + viết scripts/<slug>.json đầy đủ (compliance.passed=true)\n"
        "  2. GHI NGAY vào assets/auto_state.json (append item vào mảng đúng — "
        "long_videos hoặc short_videos trong batch key mới nhất; schema: "
        "slug/topic/orientation/render_provider/dry_run/publish_at/"
        "stage=\"ideation\"/status=\"ok\"/updated)\n"
        "  3. GHI NGAY 1 dòng vào data/ledger.md\n"
        "  4. Chỉ sau khi đã ghi xong cả 2 file mới được bắt đầu video tiếp theo\n\n"
        "Lý do: nếu hết token giữa chừng, `ytb batch start --resume` đọc "
        "auto_state.json để biết đã có bao nhiêu và chỉ viết phần còn thiếu.\n\n"
        "TUYỆT ĐỐI KHÔNG chạy voiceover/render/publish. Khi đủ "
        f"{remaining} video MỚI đã có script + đăng ký xong, DỪNG lại và báo tóm tắt "
        "(slug + chủ đề từng video mới)."
    )


def build_start_prompt(num_of_vid: int, type_of_vid: str, type_of_rules: str) -> str:
    """Dựng prompt giao việc SÁNG TẠO (ideation + viết kịch bản) cho LLM.

    Đây là phần KHÔNG mô phỏng được bằng code thường — cần LLM chọn chủ đề
    (chống trùng ledger), viết narration, tự chấm cổng compliance. Sau khi LLM
    viết xong scripts/*.json + đăng ký vào auto_state.json, `ytb batch run --loop`
    mới tiếp quản phần sản xuất máy-móc (không cần LLM nữa).
    """
    vid_label = "Video dài (ngang, 12-15 phút)" if type_of_vid == "long" else "Short (dọc, 1-1.5 phút)"
    topic_guidance = (
        "TỰ chọn chủ đề hợp ngách kênh hiện tại (đọc memory dự án + ledger để biết ngách)."
        if type_of_rules == "auto"
        else (
            f"Ý tưởng người dùng đưa là RÀNG BUỘC CHÍNH: {type_of_rules}. "
            "Được chia thành nhiều góc nhìn khác nhau nhưng không được đổi sang chủ đề khác."
        )
    )
    return (
        f"Làm phần SÁNG TẠO (ideation + viết kịch bản) cho {num_of_vid} video loại "
        f"\"{vid_label}\" — dùng skill youtube-ideation, tuân thủ ĐẦY ĐỦ "
        f".claude/skills/youtube-ideation/video-quality-rules.md (cổng verify mục 0, "
        f"luật series mục 0d, độ dài mục 2a/2b). {topic_guidance}\n\n"
        f"La bàn chủ đề bắt buộc:\n{CHANNEL_EDITORIAL_BRIEF}\n\n"
        "Every section MUST include time_goal as a positive JSON number of minutes; never 0/null/string/timestamp/range (examples: 0.5, 0.75, 1.0). The sum of time_goal values must approximately match the target duration.\n\n"
        "Trước khi chọn chủ đề: đọc data/ledger.md, loại bỏ mọi chủ đề trùng/tương tự "
        "(mọi status, không chỉ done).\n\n"
        "QUY TRÌNH BẮT BUỘC — làm TUẦN TỰ từng video, KHÔNG làm batch:\n"
        "  1. Chọn chủ đề + viết scripts/<slug>.json đầy đủ (compliance.passed=true)\n"
        "  2. GHI NGAY vào assets/auto_state.json (append item vào mảng đúng — "
        "long_videos hoặc short_videos trong batch key mới nhất; schema: "
        "slug/topic/orientation/render_provider/dry_run/publish_at/"
        "stage=\"ideation\"/status=\"ok\"/updated)\n"
        "  3. GHI NGAY 1 dòng vào data/ledger.md\n"
        "  4. Chỉ sau khi đã ghi xong cả 2 file mới được bắt đầu video tiếp theo\n\n"
        "Lý do: nếu hết token giữa chừng, `ytb batch start --resume` sẽ đọc "
        "auto_state.json để biết đã có bao nhiêu script và KHÔNG viết lại — "
        "chỉ hoạt động đúng nếu mỗi video được ghi ngay sau khi xong.\n\n"
        "TUYỆT ĐỐI KHÔNG chạy voiceover/render/publish — đó là việc của "
        "`ytb batch run --loop` chạy bằng tay sau, không cần LLM. Khi đủ "
        f"{num_of_vid} video đã có script + đăng ký xong, DỪNG lại và báo tóm tắt "
        "(slug + chủ đề từng video)."
    )


def ledger_topics(ledger_text: str) -> list[str]:
    """Cột 'Tiêu đề' từ text ledger.md — dùng làm blacklist chủ đề đã làm."""
    topics: list[str] = []
    for line in ledger_text.splitlines():
        if not line.startswith("|"):
            continue
        cols = [part.strip() for part in line.strip("|").split("|")]
        if len(cols) >= 3 and cols[2] and cols[2].lower() != "tiêu đề":
            topics.append(cols[2])
    return topics


def local_script_prompt(
    index: int,
    total: int,
    type_of_vid: str,
    type_of_rules: str,
    ledger_text: str,
    generated_summaries: list[str] | None = None,
    analytics_feedback: list[str] | None = None,
    funnel: dict[str, str] | None = None,
    source_long_context: dict | None = None,
    *,
    content_profile: "ContentProfile | None" = None,
) -> str:
    """Prompt sinh 1 script JSON qua local/structured LLM (khác luồng Claude skill)."""
    normalized_type = (type_of_vid or "").strip().lower()
    if normalized_type not in {"short", "long"}:
        raise ContentProfileError(f"video_type không hợp lệ: {type_of_vid!r}.")
    if content_profile is not None and not content_profile.supports_generation(normalized_type):
        raise ContentProfileError(
            f"Profile '{content_profile.profile_id}' không cho sinh {normalized_type} mới."
        )
    short_contract = contract_for("short", content_profile) if normalized_type == "short" else None
    long_contract = contract_for("long", content_profile) if normalized_type == "long" else None
    short_format = (
        content_profile.format_for("short")
        if content_profile is not None and normalized_type == "short"
        else None
    )
    long_format = (
        content_profile.format_for("long")
        if content_profile is not None and normalized_type == "long"
        else None
    )
    short_sections = short_format.min_sections if short_format else SHORT_PROMPT_SECTIONS
    short_max_sections = short_format.max_sections if short_format else short_sections
    long_max_sections = (
        long_format.max_sections if long_format else int(LONG_CONTRACT.minimum_sections * 1.5)
    )
    tts_provider = content_profile.providers.tts if content_profile else settings.tts_provider
    short_rate = (
        effective_chars_per_min(tts_provider, video_type="short", content_profile=content_profile)
        if normalized_type == "short" else 0.0
    )
    long_rate = (
        effective_chars_per_min(tts_provider, video_type="long", content_profile=content_profile)
        if normalized_type == "long" else 0.0
    )
    short_safe = (
        short_contract.safe_character_bounds(chars_per_minute=short_rate, segment_count=short_sections)
        if short_contract is not None else (0, 0)
    )
    short_absolute_seconds = (
        short_contract.audio_runtime_bounds_sec(segment_count=short_sections)
        if short_contract is not None else (0.0, 0.0)
    )
    short_absolute = tuple(int(short_rate * seconds / 60) for seconds in short_absolute_seconds)
    long_sections = long_format.min_sections if long_format else LONG_CONTRACT.minimum_sections
    long_safe = (
        long_contract.safe_character_bounds(chars_per_minute=long_rate, segment_count=long_sections)
        if long_contract is not None else (0, 0)
    )
    long_minutes = (
        tuple(value / 60 for value in long_contract.viewer_runtime_bounds_sec)
        if long_contract is not None else (0.0, 0.0)
    )
    editorial_brief = (
        "\n\n".join(filter(None, (
            content_profile.prompt_text("editorial"),
            content_profile.format_prompt_text(normalized_type),
        )))
        if content_profile else CHANNEL_EDITORIAL_BRIEF
    )
    # Ngân sách MỖI SECTION, suy ra từ tổng và số section cho phép.  Short đã có
    # bảng này; Long thì không, nên model chọn đúng số section rồi viết mỗi
    # section dài bằng một beat của Short — 16 section x 146 ký tự cho một Long
    # cần 5.822. Nêu rõ phép chia là đòn bẩy còn thiếu.
    def _per_section(total_chars: int, sections: int) -> int:
        return int(total_chars / max(1, sections))

    long_per_section = (
        f"With {long_sections} sections that is about "
        f"{_per_section(long_safe[0], long_sections):,} characters each; with "
        f"{long_max_sections} sections about "
        f"{_per_section(long_safe[0], long_max_sections):,} each. "
        "Count the combined voiceover before responding and lengthen scenes — "
        "never duplicate one — if the total falls short"
    ) if type_of_vid == "long" else ""

    target = (
        (
            (
                f'"video_type": "long", "target_minutes": {LONG_MIN_MINUTES} (declare EXACTLY {LONG_MIN_MINUTES}), total narration '
                f'{LONG_SAFE_MIN_CHARS}-{LONG_SAFE_MAX_CHARS} Vietnamese characters ({LONG_MIN_MINUTES}-{LONG_MAX_MINUTES} min at '
                f'{PLANNING_CHARS_PER_MIN:.0f} chars/min; actual audio must stay inside that range), and '
                f'{LONG_CONTRACT.minimum_sections}-{long_max_sections} rich sections. {long_per_section}'
            )
            if content_profile is None
            else (
                f'"video_type": "long", "target_minutes": {long_minutes[0]:g}, total narration '
                f'{long_safe[0]}-{long_safe[1]} Vietnamese characters ({long_minutes[0]:g}-{long_minutes[1]:g} min at '
                f'{long_rate:.0f} chars/min; actual audio must stay inside that range), and '
                f'{long_sections}-{long_max_sections} rich sections. {long_per_section}'
            )
        )
        if type_of_vid == "long"
        else (
            '"video_type": "short", no target_minutes, and total narration '
            f'{short_safe[0]:,}-{short_safe[1]:,} Vietnamese characters (safe target inside the '
            f'absolute {short_absolute[0]}-{short_absolute[1]} range) for a '
            f'{short_contract.viewer_runtime_bounds_sec[0]:g}-{short_contract.viewer_runtime_bounds_sec[1]:g} second Short'
        )
    )
    generated_summaries = generated_summaries or []
    analytics_feedback = analytics_feedback or []
    topic = (
        "Pick a non-duplicate topic from the channel niche."
        if type_of_rules == "auto"
        else (
            "User idea is the primary constraint. Build this script around the exact idea, "
            f"without drifting to another topic: {type_of_rules}"
        )
    )
    blocked_titles = "\n".join(f"- {title}" for title in ledger_topics(ledger_text)[-40:])
    generated = "\n".join(f"- {item}" for item in generated_summaries) or "- none yet"
    feedback = "\n".join(f"- {item}" for item in analytics_feedback) or "- no mature data yet"
    funnel = funnel or {}
    funnel_instruction = ""
    if type_of_vid == "short" and any(funnel.values()):
        funnel_instruction = (
            "\nFunnel contract for this Short: its CTA must lead to the specified long form. "
            f"long_form_slug={funnel.get('long_form_slug', '')}; "
            f"playlist={funnel.get('playlist', '')}; "
            f"cta_target={funnel.get('cta_target', '')}. "
            "Make the final spoken CTA point to that exact long-form topic.\n"
        )
    source_long_instruction = ""
    if type_of_vid == "short" and source_long_context:
        candidates = source_long_context.get("candidates", [])
        candidate_text = "\n".join(
            "- section_index={section_index}; purpose={purpose}; excerpt={excerpt}".format(
                section_index=item.get("section_index"),
                purpose=item.get("purpose", ""),
                excerpt=item.get("excerpt", ""),
            )
            for item in candidates
        )
        source_long_instruction = (
            "\nLong-derived Short contract: choose EXACTLY one source candidate below. It must be the "
            "intersection of a concrete value and an unresolved curiosity, never a generic introduction, "
            "retention beat, closing, or CTA. In strategy include source_long_slug, source_section_index, "
            "and source_excerpt; source_excerpt must exactly equal the selected candidate excerpt. Preserve "
            "the source segment's substantive claim and evidence scope. Add only a tension hook, a concise "
            "everyday context or example, a low-risk observation step, and the funnel CTA. Do not add a new "
            "factual claim unless it is covered by the evidence_register.\n"
            f"Source Long: slug={source_long_context.get('slug', '')}; title={source_long_context.get('title', '')}\n"
            f"Eligible source candidates:\n{candidate_text}\n"
            "For every factual or research claim retained from the source segment, reuse the matching source "
            "row from this Source Long evidence register; do not invent or substitute a citation.\n"
            f"Source Long evidence register: {json.dumps(source_long_context.get('evidence_register', []), ensure_ascii=False)}\n"
        )
    format_name = "long-form video" if type_of_vid == "long" else "Short"
    target_minutes_field = (
        f'"target_minutes" is required for a Long and must be the JSON number {long_minutes[0]:g}.'
        if type_of_vid == "long"
        else 'Do not include "target_minutes" for a Short.'
    )
    pexels_rule = (
            "- Add grounded Pexels queries for real stock footage.\n"
        if content_profile is None or content_profile.content_rules.require_pexels_query
        else ""
    )
    if type_of_rules == "auto":
        custom_rules = ""
    elif content_profile is not None:
        custom_rules = (
            "\nCustom idea rules:\n"
            "- The user's idea selects the episode/topic, while every declared profile rule, "
            "character fact, continuity fact, and format contract still applies.\n"
            "- Use the ledger ONLY as a blacklist of topics/titles to avoid, not as inspiration.\n"
            f"- Requested idea: {type_of_rules}\n"
            f"{pexels_rule}"
            "- Keep narration natural in Vietnamese and derive the insight from this exact scene.\n"
        )
    else:
        custom_rules = (
            "\nCustom idea rules:\n"
            "- The user's idea overrides the default channel niche and old ledger topics.\n"
            "- Use the ledger ONLY as a blacklist of topics/titles to avoid, not as inspiration.\n"
            "- Current channel scope is sharing/knowledge, not entertainment. Do NOT write comedy, "
            "punchline structure, or gag narration for this channel.\n"
            f"- Write a clear Vietnamese knowledge {format_name}: concrete everyday example, "
            "mechanism, and an application step.\n"
            f"{pexels_rule}"
            "- The narration must contain a concrete everyday example and an actionable application "
            "in natural Vietnamese; do not use fixed labels or template phrases.\n"
        )
    requires_strategy = (
        type_of_vid == "short"
        and (
            content_profile is None
            or content_profile.content_rules.require_short_source_trace
        )
    )
    strategy_instruction = (
        f"\nStrategy-v1 contract:\n{STRATEGY_V1_CONTRACT}\n"
        if requires_strategy
        else (
            "\nFor a Long, omit strategy; its single mechanism and series bridge belong in the narration.\n"
            if type_of_vid == "long"
            else "\nFor this character-story Short, omit strategy; conflict, choice and consequence belong in the scene.\n"
        )
    )
    strategy_schema = '"strategy", ' if requires_strategy else ""
    financial_source_contract = personal_finance_source_contract(type_of_rules)
    financial_schema = '"editorial_profile", "evidence_register", ' if financial_source_contract else ""
    uniqueness_instruction = (
        "This Short may reuse the declared source Long only. Do not reuse any existing Short's slug, "
        "title, source section, scene setup, or punchline listed below.\n"
        if type_of_vid == "short" and source_long_context else
        "This must be a NEW concept inside the current batch. Do not reuse any slug, title, "
        "topic, scene setup, or punchline already listed below.\n"
    )
    profile_fields = (
        f'profile_id (exactly "{content_profile.profile_id}"), '
        f'profile_version (exactly "{content_profile.version}"), '
        if content_profile else ""
    )
    auto_visuals = bool(
        content_profile and content_profile.visual_generation and content_profile.visual_generation.enabled
    )
    if content_profile and content_profile.narrative_mode == "character_story":
        cast_ids = sorted(
            name for name in content_profile.voice_cast
            if name != content_profile.editorial_contract.narration_speaker_id
        )
        section_fields = (
            f"Each section also needs speaker_id and scene_characters (array subset of {cast_ids}, "
            "at most 2, listing who is VISIBLE in this frame; use [] for an establishing/prop shot). "
            + (
                "Each section also needs turn: narrator uses null; a character uses an object with "
                "scene, intent, and responds_to (null or a previous one-based section number). "
                if content_profile.content_rules.require_conversation_turns else ""
            )
            if auto_visuals
            else "Each section also needs speaker_id and visual_asset; visual_asset is a filename under the profile assets directory. "
        )
    else:
        section_fields = "Each section also needs pexels_query. "
    short_instruction = "" if type_of_vid != "short" else (
        f"Use exactly {short_sections} sections for this Short. Make `situation` first and "
        f"keep it under {short_contract.situation_char_budget(chars_per_minute=short_rate)} characters with a concrete tension marker; "
        "make `core_answer` the next section and begin with the exact strategy.hook.core_answer. "
        "This immediate answer contract is mandatory.\n"
        if requires_strategy
        else f"Use exactly {short_sections} sections for this Short unless the profile allows a story beat expansion up to {short_max_sections}. Follow the profile's spoken-language and continuity rules.\n"
    )
    visual_asset_instruction = ""
    if content_profile and content_profile.narrative_mode == "character_story":
        if auto_visuals:
            cast_ids = sorted(
                name for name in content_profile.voice_cast
                if name != content_profile.editorial_contract.narration_speaker_id
            )
            visual_asset_instruction = (
                f"scene_characters lists who is on screen, from {cast_ids}, max 2 — "
                "never a filename, never more than the two the profile can render together.\n"
            )
        else:
            names = ", ".join(content_profile.visual_asset_names)
            visual_asset_instruction = (
                "Use only these visual_asset filenames; never invent a path or filename: "
                f"{names or '<no scene assets configured>'}.\n"
            )
        # Ledger được ghi từ chính tuyên bố này sau khi tập lên sóng, nên nó phải
        # mô tả tập NÀY, không phải tóm tắt lại series. Áp dụng cho mọi profile
        # character_story, không phụ thuộc auto_visuals.
        visual_asset_instruction += (
            "Also return a `continuity` object recording what THIS episode changed, "
            "so the next episode can be written on top of it: episode_summary (one "
            "sentence naming the choice made and its consequence), character_changes "
            "(object mapping a cast id to what changed for that character; use {} if "
            "nothing changed), threads_opened and threads_closed (arrays of short "
            "Vietnamese sentences; use [] when empty). Do not restate the series "
            "premise and do not invent events outside this episode.\n"
            # Hai luật này trước đây chỉ tồn tại ở cổng QA, nên model chỉ biết
            # sau khi đã bị từ chối một lượt sinh.
            "Never prefix a line with the speaker name (write \"Cậu mở hộp thư "
            "lần thứ mấy rồi?\", not \"An: Cậu mở hộp thư...\") — speaker_id "
            "already routes the voice and the prefix gets read aloud. "
            + (
                f"{_story_series_role_instruction(content_profile)} "
                f"{_character_story_closing_instruction(content_profile)}\n"
                if normalized_type == "long"
                else ""
            )
            + f"{STORY_HOOK_CONTRACT}\n"
        )
    opening_instruction = (
        _long_opening_instruction(content_profile) + "\n"
        if content_profile is not None and normalized_type == "long"
        else ""
    )
    closing_instruction = (
        _long_closing_instruction(content_profile) + "\n"
        if content_profile is not None and normalized_type == "long"
        else ""
    )
    short_ending_instruction = (
        _short_ending_instruction(content_profile) + "\n"
        if content_profile is not None and normalized_type == "short"
        else ""
    )
    return (
        "You are writing a Vietnamese YouTube script JSON for a local-first pipeline.\n"
        f"Video {index}/{total}. Type: {type_of_vid}. Requirement: {topic}\n"
        f"Content profile editorial compass:\n{editorial_brief}\n"
        f"{opening_instruction}"
        f"{closing_instruction}"
        f"{short_ending_instruction}"
        f"{strategy_instruction}"
        f"Length contract: {target}.\n"
        f"{funnel_instruction}"
        f"{source_long_instruction}"
        f"{financial_source_contract}"
        f"{uniqueness_instruction}"
        f"{custom_rules}\n"
        "Already generated in this batch:\n"
        f"{generated}\n\n"
        "Analytics decisions from mature previous videos: \n"
        f"{feedback}\n"
        "Do not repeat formats labelled drop_format; for revise_hook/revise_value, change the named component.\n\n"
        "Blocked historical titles/topics:\n"
        f"{blocked_titles or '- none'}\n\n"
        "Return ONLY one JSON object with keys: slug, topic, title, description, tags, "
        f"{profile_fields}"
        f"video_type, target_minutes, voice_profile, \"thumbnail_brief\", {financial_schema}{strategy_schema}sections, compliance. video_type is only long or short. "
        f"{target_minutes_field} "
        "voice_profile is knowledge or inspiring. Each section needs time_goal as a positive JSON number of minutes (never 0/null/string/timestamp/range), purpose, voiceover, "
        "visual_intent, caption, hook, transition, payoff, emphasis. "
        f"{section_fields}"
        f"{visual_asset_instruction}"
        "Use these canonical fields only; the pipeline reads voiceover and pexels_query directly.\n"
        "thumbnail_brief is required for this newly generated script and has exactly four non-empty string fields: visual_contradiction, subject, emotion, headline. "
        "Make the visual_contradiction immediately legible, name a concrete subject and one emotion, and use a headline of 4 words or fewer (never the full title).\n"
        "compliance.passed must be true and include community/copyright/accuracy/"
        "advertiser/coppa/notes."
        f"{short_instruction}"
    )


def _long_extension_field_rule(content_profile: "ContentProfile | None") -> str:
    """Field guidance a new Long section must follow, sourced from the profile.

    This used to hardcode `pexels_query` as required on every added section —
    correct for the explainer channel, but a story profile with auto-generated
    scenes has no Pexels field at all, and Long extension paid for an LLM call
    whose sections were then rejected by script_contract for having the wrong
    shape. Every field this text asks for must be exactly what the profile's
    own required-field policy (mirrored in generation_schema/script_contract)
    will accept.
    """
    base = "purpose, time_goal (a positive number), voiceover, visual_intent"
    if content_profile is None:
        return f"Each new section must have {base}, pexels_query, caption, hook, transition, payoff, and emphasis."
    if content_profile.narrative_mode == "character_story":
        vg = content_profile.visual_generation
        narrator_id = content_profile.editorial_contract.narration_speaker_id
        auto_visuals = vg is not None and vg.enabled
        if auto_visuals:
            cast_ids = sorted(name for name in content_profile.voice_cast if name != narrator_id)
            visual_field = (
                f"scene_characters (array subset of {cast_ids}, at most 2, [] for no one "
                "visible — never invent visual_asset)"
            )
        else:
            visual_field = "visual_asset (a filename under the profile assets directory)"
        rule = f"Each new section must have {base}, speaker_id, {visual_field}, caption, hook, transition, payoff, and emphasis."
        if content_profile.content_rules.require_conversation_turns:
            rule += (
                " Each new section also needs turn: narrator sections set turn=null; a character "
                "section sets turn to an object with non-empty scene and intent, and responds_to as "
                "null or a previous one-based section number it answers."
            )
        return rule
    pexels_clause = ", pexels_query" if content_profile.content_rules.require_pexels_query else ""
    return f"Each new section must have {base}{pexels_clause}, caption, hook, transition, payoff, and emphasis."


def long_extension_prompt(
    payload: dict,
    missing_chars: int,
    *,
    max_new_sections: int | None = None,
    content_profile: "ContentProfile | None" = None,
) -> str:
    """Ask for only the missing Long sections, keeping one Codex response bounded."""
    context = {
        key: payload.get(key)
        for key in ("slug", "topic", "title", "description", "tags", "voice_profile", "compliance")
    }
    context["existing_sections"] = [
        {**section, "section_index": index}
        for index, section in enumerate(payload.get("sections", []) or (), start=1)
        if isinstance(section, dict)
    ]
    if max_new_sections == 1:
        section_count_instruction = "Add 1 new, topic-specific section "
    elif max_new_sections is not None:
        section_count_instruction = f"Add 1-{max_new_sections} new, topic-specific sections "
    else:
        section_count_instruction = "Add only as many new, topic-specific sections as are needed "
    field_rule = _long_extension_field_rule(content_profile)
    return (
        "Extend a Vietnamese long-form YouTube script without rewriting its existing narration.\n"
        "Return ONLY one JSON object with a `sections` array and `insert_before_section_index`; do not return the full script or markdown. "
        "insert_before_section_index is the one-based section_index of an EXISTING section that the new material must come immediately before. "
        "Choose the chronological boundary from the supplied story: the first event in your additions must happen before that target section, never after a later time jump, flash-forward, meeting, or conclusion.\n"
        f"Do not rewrite, repeat, or summarize the existing sections. {section_count_instruction}"
        f"whose combined `voiceover` is at least {missing_chars:,} Vietnamese characters. {field_rule} Develop only the "
        "same named mechanism through fresh evidence, concrete examples, limits, or applications. Prefer the fewest "
        "complete beats that satisfy the missing runtime. Do not add a "
        "second greeting, a duplicate CTA, a generic self-help list, or unsupported factual claims.\n\n"
        f"Script context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def short_expansion_allowed_indexes(
    payload: dict,
    *,
    content_profile: "ContentProfile | None" = None,
) -> tuple[int, ...]:
    """Return mutable Short beat indexes using the engine's zero-based contract.

    Array position cannot determine what is safe to edit. Each profile declares
    repairable purposes; the hook and final CTA always remain immutable. Scripts
    without a profile preserve the documented legacy policy.
    """
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return ()
    if content_profile is None:
        profile_id = str(payload.get("profile_id") or "").strip()
        content_profile = load_content_profile(profile_id) if profile_id else None
    repairable_purposes = {
        purpose.strip().casefold()
        for purpose in (
            content_profile.editorial_contract.short_expansion_purposes
            if content_profile is not None
            else LEGACY_SHORT_EXPANSION_PURPOSES
        )
    }
    last_index = len(sections) - 1
    return tuple(
        index
        for index, section in enumerate(sections)
        if isinstance(section, dict)
        and index != last_index
        and not bool(section.get("hook"))
        and str(section.get("purpose") or "").strip().casefold() in repairable_purposes
    )


def short_expansion_prompt(
    payload: dict,
    missing_chars: int,
    *,
    target_chars: int | None = None,
    max_chars: int | None = None,
    content_profile: "ContentProfile | None" = None,
) -> str:
    """Ask for one bounded Short addition, never a rewrite or CTA edit."""
    context = {
        key: payload.get(key)
        for key in ("slug", "topic", "title", "strategy", "compliance")
    }
    context["sections"] = payload.get("sections", [])
    allowed_indexes = short_expansion_allowed_indexes(
        payload, content_profile=content_profile,
    )
    target_clause = (
        f" aim for {target_chars:,} characters."
        if target_chars is not None else ""
    )
    maximum_clause = (
        f" use at most {max_chars:,} characters."
        if max_chars is not None else ""
    )
    return (
        "Expand only the underdeveloped middle narration of this Vietnamese Short.\n"
        "Return ONLY one JSON object with a `section_updates` array. Do not return the full script "
        "or markdown. `index` is a ZERO-BASED JSON array index, not a human section number. "
        "Return exactly ONE item shaped `{\"index\": <allowed zero-based index>, "
        "\"append_voiceover\": <new Vietnamese text>}`. "
        f"ONLY legal index values: {list(allowed_indexes)}. Do not change title, metadata, hook, "
        "source trace, section order, the first situation/core_answer sections, or the final payoff/CTA. "
        "Add a specific topic-relevant explanation, example, or action that follows the chosen existing "
        "section. Do not introduce a new person, place, event, or outcome outside that section's context. "
        f"The appended text must be at least {missing_chars:,} characters.{target_clause}{maximum_clause} "
        "Do not add greetings, duplicated CTA, generic self-help, or unsupported claims.\n\n"
        f"Script context:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def repair_prompt(
    payload: dict,
    qa_output: dict | None,
    validation_error: str | None,
    recovery_directive: str = "",
) -> str:
    """Prompt yêu cầu LLM sửa script JSON không qua validation/QA."""
    issues = {
        "validation_error": validation_error,
        "qa": qa_output or {},
    }
    is_financial_psychology = (
        payload.get("editorial_profile") == PERSONAL_FINANCE_PSYCHOLOGY_PROFILE
        or isinstance(payload.get("evidence_register"), list)
        or "financial script" in (validation_error or "").casefold()
    )
    financial_repair_contract = (
        "Preserve editorial_profile=personal_finance_psychology exactly. Preserve the complete "
        "evidence_register and every source URL unless a source itself is invalid; do not replace "
        "a cited claim with an uncited claim. Keep compliance.accuracy explicitly confirming that "
        "the evidence_register covers every factual financial, psychological, or research claim. "
        "Remove any wording that predicts the same financial behaviour or outcome for all people; "
        "state the research scope and its limits instead.\n"
        if is_financial_psychology
        else ""
    )
    financial_schema = "editorial_profile, evidence_register, " if is_financial_psychology else ""
    repair_profile_id = str(payload.get("profile_id") or "").strip()
    repair_profile = load_content_profile(repair_profile_id) if repair_profile_id else None
    hook_repair_rule = (
        "Rewrite the first narration section whenever the QA issues include rule "
        f"'hook': {_hook_repair_directive(repair_profile)}\n"
    )
    return (
        "Repair this Vietnamese YouTube script JSON for the local-first pipeline.\n"
        "Return ONLY the full corrected JSON object. Do not add markdown.\n"
        "Preserve the topic and core story unless a listed violation requires a narrow fix.\n"
        "If Current JSON already has a strategy object, preserve it. For a strategy-v1 Short, keep "
        "format_id, core_mechanism, audience_problem, angle, long_form_slug, playlist, cta_target, "
        "source_long_slug, source_section_index, source_excerpt, and hook; retain a situation section followed by a core_answer section whose narration STARTS with "
        "the exact hook.core_answer before hook.answer_by_sec seconds.\n"
        f"{financial_repair_contract}"
        f"For Shorts without target_minutes, total narration MUST be {SHORT_MIN_CHARS}-{SHORT_MAX_CHARS} "
        f"Vietnamese characters for {SHORT_MIN_MINUTES:.2f}-{SHORT_MAX_MINUTES:.2f} minutes. Do not overshoot. Do not add greetings. "
        f"For Longs, target_minutes MUST be EXACTLY {LONG_MIN_MINUTES} and total narration MUST be "
        f"{LONG_SAFE_MIN_CHARS}-{LONG_SAFE_MAX_CHARS} Vietnamese characters ({LONG_MIN_MINUTES}-{LONG_MAX_MINUTES} minutes at "
        f"{PLANNING_CHARS_PER_MIN:.0f} chars/min); measured "
        f"minutes = total_chars / {PLANNING_CHARS_PER_MIN:.0f} must be >= target_minutes and <= {LONG_MAX_MINUTES}. "
        "If the script is too short, retain every valid existing narration section and add the missing specific "
        "narration until the actual voiceover character count is inside the Long range. Do not shorten or delete "
        "valid existing narration; every added sentence must remain specific to the declared title and topic, never "
        "reuse generic examples, mechanisms, or application steps from another video.\n"
        "Current channel scope is sharing/knowledge, not entertainment. Remove comedy, "
        "punchline, and gag narration if present. Keep a concrete "
        "everyday example, mechanism, application step, and real-stock-footage Pexels queries.\n"
        "If review reports a missing example, repair the narration with a specific everyday context, observable action, consequence, and practical application in natural Vietnamese. Do not add fixed labels merely to satisfy a parser.\n"
        "For both Shorts and Longs, retain or add at most one value-first retention beat only where it follows a concrete insight: acknowledge the topic-specific value just delivered, then make a brief natural invitation to like or follow/subscribe. Do not use a fixed sentence, repeat it across sections, or place it before the hook.\n"
        f"{hook_repair_rule}"
        "Required schema: slug, topic, title, description, tags, video_type, target_minutes, voice_profile, "
        f"{financial_schema}strategy, sections, compliance. video_type is only short or long. \"target_minutes\" is required for a Long "
        f"and must be the JSON number {LONG_MIN_MINUTES}; omit it for a Short. voice_profile is knowledge "
        "or inspiring. Each section needs time_goal as a positive JSON number of minutes (never 0/null/string/timestamp/range; examples 0.5, 0.75, 1.0), voiceover, visual_intent, pexels_query, "
        "caption, hook, transition, payoff, emphasis, purpose. Use these canonical fields only. "
        "compliance.passed must be true.\n\n"
        f"Recovery directive:\n{recovery_directive or 'Apply the listed validation and QA fixes.'}\n\n"
        f"Issues:\n{json.dumps(issues, ensure_ascii=False, indent=2)}\n\n"
        f"Current JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )
