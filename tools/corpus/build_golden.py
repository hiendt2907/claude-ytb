"""Build the golden corpus: real artifacts paired with the verdict they got.

Six later steps compare against this corpus, so it is committed data, not a
scratch file, and the build must be deterministic — same repository state, same
bytes out. Human labels live in a SEPARATE file so rebuilding never overwrites
them.

The join is exact rather than heuristic: `editorial_review_cache/<profile>/` is
keyed by `sha256(profile_fingerprint + canonical payload)`, so a script can be
matched to its own review by recomputing that key. This module imports the real
key functions instead of reimplementing them — a second copy of a hash function
is precisely the drift that has already cost this repository several days.

    PYTHONPATH=src .venv/bin/python tools/corpus/build_golden.py --report
    PYTHONPATH=src .venv/bin/python tools/corpus/build_golden.py --write
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ytb_pipeline.agents.editorial_review_agent import _cache_key, _reviewable_payload
from ytb_pipeline.content_profiles import ContentProfile, load_content_profile

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = ROOT / "assets" / "golden_corpus"
REVIEW_CACHE = ROOT / "assets" / "editorial_review_cache"

# Where candidate scripts live. `script_revisions/` holds superseded and
# rejected drafts — exactly the negative examples a calibration set needs.
_SCRIPT_GLOBS = ("scripts/*.json", "assets/script_revisions/**/*.json")

# How many entries to carry per (profile, passed) bucket. Stratified so the
# corpus cannot become 90% failures just because failures are more numerous.
_PER_BUCKET = 14

_EDITORIAL_DIMENSIONS = (
    "causal_coherence",
    "human_truth",
    "role_fidelity",
    "spoken_naturalness",
    "useful_restraint",
)


@dataclass(frozen=True)
class Entry:
    entry_id: str
    profile_id: str
    profile_version: str
    video_type: str
    slug: str
    title: str
    source: str
    section_count: int
    total_chars: int
    machine_passed: bool
    # Rubric scores exist only for the drafts whose review is still joinable by
    # hash. A saved revision is usually the repaired text while the review
    # scored the text BEFORE repair, so most entries carry the recorded QA
    # verdict instead — rules and reasons, which is what the deterministic
    # layer's parity tests need anyway.
    machine_overall: int | None
    machine_dimensions: dict[str, int]
    machine_findings: tuple[str, ...]
    violated_rules: tuple[str, ...]
    verdict_source: str

    def to_json(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "video_type": self.video_type,
            "slug": self.slug,
            "title": self.title,
            "source": self.source,
            "section_count": self.section_count,
            "total_chars": self.total_chars,
            "machine_verdict": {
                "source": self.verdict_source,
                "passed": self.machine_passed,
                "overall_score": self.machine_overall,
                "dimension_scores": dict(sorted(self.machine_dimensions.items())),
                "violated_rules": list(self.violated_rules),
                "blocking_findings": list(self.machine_findings),
            },
        }


def _iter_script_payloads() -> Iterator[tuple[Path, dict[str, Any]]]:
    seen: set[str] = set()
    for pattern in _SCRIPT_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or not payload.get("sections"):
                continue
            # A draft the provider corrupted mid-transfer (U+FFFD where a
            # Vietnamese character should be) was rejected by
            # `xkiro_provider`, not by any editorial judgement. It teaches
            # nothing about content quality and would put a broken transcript
            # in front of a human reviewer. 23 such drafts exist on disk.
            if "�" in path.read_text(encoding="utf-8", errors="replace"):
                continue
            # Identical drafts saved under several names must not appear twice.
            fingerprint = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            yield path, payload


_PROFILE_CACHE: dict[tuple[str, str], ContentProfile | None] = {}


def _profile_for(payload: dict[str, Any]) -> ContentProfile | None:
    profile_id = str(payload.get("profile_id") or "").strip()
    version = str(payload.get("profile_version") or "").strip()
    if not profile_id:
        return None
    key = (profile_id, version)
    if key not in _PROFILE_CACHE:
        try:
            _PROFILE_CACHE[key] = load_content_profile(
                profile_id, version=version or None
            )
        except Exception:  # a version whose snapshot was never taken
            _PROFILE_CACHE[key] = None
    return _PROFILE_CACHE[key]


def _verdict_for(profile: ContentProfile, payload: dict[str, Any]) -> dict[str, Any] | None:
    key = _cache_key(profile, _reviewable_payload(payload))
    path = REVIEW_CACHE / profile.profile_id / f"{key}.json"
    if not path.is_file():
        return None
    try:
        verdict = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return verdict if isinstance(verdict, dict) else None


def _total_chars(payload: dict[str, Any]) -> int:
    return sum(
        len(str(section.get("voiceover") or ""))
        for section in payload.get("sections", [])
        if isinstance(section, dict)
    )


def _inline_qa(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The QA verdict the pipeline recorded on the script itself."""
    review = payload.get("quality_review")
    if not isinstance(review, dict):
        return None
    qa = review.get("qa")
    return qa if isinstance(qa, dict) else None


def _payload_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:16]


def collect() -> tuple[list[Entry], Counter[str]]:
    """Every script carrying a recorded verdict, from either source."""
    entries: list[Entry] = []
    stats: Counter[str] = Counter()
    for path, payload in _iter_script_payloads():
        stats["scripts_scanned"] += 1
        profile = _profile_for(payload)

        rubric = _verdict_for(profile, payload) if profile is not None else None
        dimensions: dict[str, int] = {}
        overall: int | None = None
        findings: tuple[str, ...] = ()
        source = ""
        passed = False

        if rubric is not None and set(rubric.get("dimension_scores") or {}) == set(
            _EDITORIAL_DIMENSIONS
        ):
            stats["rubric_joined"] += 1
            source = "editorial_review_cache"
            passed = bool(rubric.get("passed"))
            overall = int(rubric.get("overall_score") or 0)
            dimensions = {k: int(v) for k, v in rubric["dimension_scores"].items()}
            findings = tuple(str(f) for f in rubric.get("blocking_findings", []))

        qa = _inline_qa(payload)
        rules: tuple[str, ...] = ()
        if qa is not None:
            rules = tuple(
                sorted(
                    {
                        str(v.get("rule"))
                        for v in qa.get("violations", [])
                        if isinstance(v, dict) and v.get("rule")
                    }
                )
            )
            if not source:
                stats["qa_only"] += 1
                source = "script.quality_review.qa"
                passed = bool(qa.get("passed"))
                findings = tuple(
                    str(v.get("detail"))
                    for v in qa.get("violations", [])
                    if isinstance(v, dict) and v.get("detail")
                )

        if not source:
            stats["no_recorded_verdict"] += 1
            continue

        entries.append(
            Entry(
                entry_id=_payload_id(payload),
                profile_id=(
                    profile.profile_id if profile is not None
                    else str(payload.get("profile_id") or "legacy-pre-profile")
                ),
                profile_version=str(payload.get("profile_version") or ""),
                video_type=str(payload.get("video_type") or "long"),
                slug=str(payload.get("slug") or ""),
                title=str(payload.get("title") or ""),
                source=str(path.relative_to(ROOT)),
                section_count=len(payload.get("sections", [])),
                total_chars=_total_chars(payload),
                machine_passed=passed,
                machine_overall=overall,
                machine_dimensions=dimensions,
                machine_findings=findings,
                violated_rules=rules,
                verdict_source=source,
            )
        )
    return entries, stats


def stratify(entries: list[Entry], per_bucket: int = _PER_BUCKET) -> list[Entry]:
    """Balanced sample, chosen by entry_id so the result is reproducible.

    Bucketing includes `video_type`. Without it the first build drew 13 Shorts
    against 9 Longs for ban-so-6 — a series that is Long-only by ratified
    decision — so most of the sample measured a format the profile does not
    produce, and the labelling round spent on it said nothing about the Long
    pipeline being refactored.
    """
    buckets: dict[tuple[str, str, bool], list[Entry]] = {}
    for entry in entries:
        key = (entry.profile_id, entry.video_type, entry.machine_passed)
        buckets.setdefault(key, []).append(entry)
    chosen: list[Entry] = []
    for key in sorted(buckets):
        # Sorting by entry_id is a content-derived order: stable across runs and
        # across machines, and it does not favour recent drafts.
        chosen.extend(sorted(buckets[key], key=lambda e: e.entry_id)[:per_bucket])
    return sorted(chosen, key=lambda e: e.entry_id)


def write(entries: list[Entry]) -> Path:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    corpus_path = CORPUS_DIR / "editorial.json"
    body = {
        "schema_version": 1,
        "dimensions": list(_EDITORIAL_DIMENSIONS),
        "entries": [entry.to_json() for entry in entries],
    }
    text = json.dumps(body, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    corpus_path.write_text(text, encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "entry_count": len(entries),
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "by_profile": dict(sorted(Counter(e.profile_id for e in entries).items())),
        "machine_passed": sum(1 for e in entries if e.machine_passed),
        "machine_failed": sum(1 for e in entries if not e.machine_passed),
    }
    (CORPUS_DIR / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return corpus_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the corpus to disk")
    parser.add_argument("--per-bucket", type=int, default=_PER_BUCKET)
    args = parser.parse_args()

    entries, stats = collect()
    sample = stratify(entries, per_bucket=args.per_bucket)

    print("nguon:")
    for key in sorted(stats):
        print(f"  {key:24s} {stats[key]}")
    print(f"\nnoi duoc: {len(entries)}  ->  mau phan tang: {len(sample)}")
    for (profile_id, passed), count in sorted(
        Counter((e.profile_id, e.machine_passed) for e in sample).items()
    ):
        print(f"  {profile_id:20s} {'passed' if passed else 'failed'}: {count}")

    if args.write:
        path = write(sample)
        print(f"\nda ghi: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
