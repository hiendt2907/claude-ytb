"""Whether the engine may settle a rejected shot itself, and on what terms.

When every candidate for a shot is rejected, `VisualAssetResolver` raises
`ReviewRequiredError` and the run halts until a person decides. That is the
right default and stays the default. But four ban-so-6 Longs sat halted from
2026-09-03 with the whole pipeline complete up to that one node, so the halt
was not protecting quality — it was just where the work stopped.

The measurement that shapes this module: across those four blocked shots, not
one candidate was free of `hard_failures`, and two scored 0.585 against a 0.5
threshold. `minimum_score` was never the gate; `rank_eligible`'s
`not evaluation.is_hard_failed()` was. Dropping the threshold to zero would
have released nothing.

So "accept the best candidate" is the wrong rule, because the best candidate is
not always acceptable. Two of the four differ in kind:

    cuoc-goi-ban-luc-bay-gio-muoi   0.585   semantic_contradiction
                                    Minh looks at his laptop instead of up
    minh-cham-hon-dong-nghiep-tre   0.285   wrong_environment + 2 more
                                    a coffee shop standing in for a meeting room

A viewer forgives the first and notices the second. The policy therefore names
which failure codes may be waived rather than ranking past all of them, and a
profile decides which those are — never this module, and never a threshold
alone. Two classes are refused even to a profile: a shot missing its character,
or showing the wrong one, is a broken episode of a series built on two
recurring faces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Mapping, Sequence

from .visual_judge import KNOWN_HARD_FAILURE_CODES

if TYPE_CHECKING:
    from .visual_judge import CandidateEvaluation

DISPOSITION_MODES = frozenset({"halt", "accept_best"})

# Waiving either of these would let the engine ship a shot whose subject is
# absent or is somebody else. No profile may opt into that.
UNWAIVABLE_HARD_FAILURES = frozenset({
    "required_character_absent",
    "wrong_main_character",
})


class DispositionError(ValueError):
    """The declared policy is not one the engine can honour."""


@dataclass(frozen=True)
class AutoDispositionPolicy:
    """How a shot the Judge rejected may be settled without a person.

    Defaults reproduce the previous behaviour exactly: halt, waive nothing.
    """

    mode: str = "halt"
    # Deliberately separate from `visual_judge.minimum_score`. That one decides
    # what passes cleanly; this one decides what is tolerable when nothing did,
    # and conflating them would move the clean bar every time the salvage bar
    # moved.
    minimum_score: float = 0.0
    ignorable_hard_failures: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.mode not in DISPOSITION_MODES:
            raise DispositionError(
                f"auto_disposition phải là một trong {sorted(DISPOSITION_MODES)}, "
                f"nhận được {self.mode!r}."
            )
        if not 0.0 <= self.minimum_score <= 1.0:
            raise DispositionError(
                "auto_accept_minimum_score phải nằm trong [0.0, 1.0]."
            )
        unknown = sorted(self.ignorable_hard_failures - KNOWN_HARD_FAILURE_CODES)
        if unknown:
            raise DispositionError(
                "auto_accept_ignorable_hard_failures chứa mã Judge không phát ra: "
                f"{', '.join(unknown)}. Một mã gõ sai sẽ không tha thứ gì cả "
                "mà vẫn trông như đã tha."
            )
        forbidden = sorted(self.ignorable_hard_failures & UNWAIVABLE_HARD_FAILURES)
        if forbidden:
            raise DispositionError(
                f"Không được bỏ qua {', '.join(forbidden)} — cảnh thiếu nhân vật "
                "hoặc sai nhân vật là tập phim hỏng, không phải vết xước."
            )

    @property
    def accepts_automatically(self) -> bool:
        return self.mode == "accept_best"


def choose_auto_accept(
    evaluations: Sequence["CandidateEvaluation"],
    *,
    policy: AutoDispositionPolicy,
    candidate_index_by_asset: Mapping[str, int],
) -> str | None:
    """The asset the engine may accept on its own, or None to keep halting.

    Mirrors `visual_judge.rank_eligible`'s ordering — highest aggregate first,
    ties broken on the earlier candidate index — so an automatic choice and a
    clean selection never disagree about which of two equals is "first".
    """
    if not policy.accepts_automatically:
        return None

    tolerable = [
        evaluation
        for evaluation in evaluations
        if not (set(evaluation.hard_failures) - policy.ignorable_hard_failures)
        and evaluation.aggregate_score() >= policy.minimum_score
    ]
    if not tolerable:
        return None
    tolerable.sort(
        key=lambda evaluation: (
            -evaluation.aggregate_score(),
            candidate_index_by_asset.get(evaluation.asset_id, 0),
        )
    )
    return tolerable[0].asset_id
