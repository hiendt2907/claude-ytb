"""The profile-authoring template must never go stale.

`docs/CONTENT_PROFILE_TEMPLATE.md` documents every field a new content
profile can declare. This test cross-checks that guide against the real
dataclasses in `content_profiles.py` so a field added to the loader without a
matching doc update fails here, instead of silently rotting until the next
profile author has to reverse-engineer it from source.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from ytb_pipeline.content_profiles import (
    ContentProfile,
    ContentRules,
    EditorialContractProfile,
    EditorialReviewProfile,
    FormatProfile,
    ProviderProfile,
    PurposePolicy,
    RenderProfile,
    VisualGenerationProfile,
    load_content_profile,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "content_profiles"
GUIDE_PATH = Path(__file__).parents[1] / "docs" / "CONTENT_PROFILE_TEMPLATE.md"

# Fields the guide is not expected to name literally: internal plumbing
# (paths, the profile's own identity fields) rather than editorial knobs an
# author chooses between.
_EXEMPT_FIELDS = frozenset({
    "root", "assets_root", "profile_id", "version", "display_name", "topic",
    "narrative_mode", "prompts", "formats", "providers", "voice_cast",
    "content_rules", "render", "editorial_contract", "vocabulary", "required",
    # Internal dataclass field names whose JSON-facing key is already
    # documented under a different, author-visible name.
    "assets_dir_name",  # JSON key is `render.assets_dir`
    "purpose_policy",  # composed from `purpose_vocabulary`/`required_purposes`
})


def test_template_fixture_loads_via_the_real_loader():
    profile = load_content_profile("template-fixture", profiles_dir=FIXTURES_ROOT)

    assert isinstance(profile, ContentProfile)
    assert profile.narrative_mode == "mechanism_explainer"
    assert profile.format_for("long").min_sections == 10


def test_template_guide_documents_every_declared_field():
    guide = GUIDE_PATH.read_text(encoding="utf-8")

    documented_dataclasses = (
        FormatProfile, ProviderProfile, ContentRules, PurposePolicy,
        EditorialContractProfile, RenderProfile, EditorialReviewProfile,
        VisualGenerationProfile,
    )
    missing: list[str] = []
    for klass in documented_dataclasses:
        for f in dataclasses.fields(klass):
            if f.name in _EXEMPT_FIELDS:
                continue
            if f.name not in guide:
                missing.append(f"{klass.__name__}.{f.name}")

    assert not missing, (
        "docs/CONTENT_PROFILE_TEMPLATE.md thiếu mô tả cho field: "
        f"{missing}. Cập nhật guide trước khi coi profile template là đúng hiện trạng."
    )
