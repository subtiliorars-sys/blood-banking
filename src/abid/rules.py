"""Antibody identification engine.

Rule-based identification of single and two-antibody cases from an antigram,
using standard exclusion logic as described in the 12th edition of Dacie &
Lewis, Practical Haematology.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional, Sequence

from .antibody import ANTIBODY_CATALOG, AntibodyCandidate
from .antigram import Antigram, CellReaction


@dataclass
class IdentificationResult:
    """Outcome of identifying one case."""

    patient_id: str
    single_antibody: Optional[AntibodyCandidate] = None
    confident_single: bool = False
    single_score: float = 0.0
    single_exclusions: List[str] = field(default_factory=list)

    pairs: List[List[str]] = field(default_factory=list)
    confident_pairs: List[List[str]] = field(default_factory=list)
    pair_scores: List[float] = field(default_factory=list)

    auto_control_positive: bool = False
    flagged: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "single_antibody": self.single_antibody.name if self.single_antibody else None,
            "confident_single": self.confident_single,
            "single_score": round(self.single_score, 3),
            "single_exclusions": self.single_exclusions,
            "pairs": [list(p) for p in self.pairs],
            "confident_pairs": [list(p) for p in self.confident_pairs],
            "pair_scores": [round(s, 3) for s in self.pair_scores],
            "auto_control_positive": self.auto_control_positive,
            "flagged": self.flagged,
            "warnings": self.warnings,
        }


def is_reactive(reaction: CellReaction) -> bool:
    return reaction.is_positive(threshold=1)


def get_positive_cells(antigram: Antigram) -> List[str]:
    return [cid for cid, r in antigram.reactions.items() if is_reactive(r)]


def get_negative_cells(antigram: Antigram) -> List[str]:
    return [
        cid for cid, r in antigram.reactions.items()
        if not is_reactive(r) and not r.autocontrol
    ]


def get_auto_control_cells(antigram: Antigram) -> List[str]:
    return [cid for cid, r in antigram.reactions.items() if r.autocontrol]


def _cells_carrying(antigram: Antigram, cell_ids: Sequence[str], antigen: str) -> List[str]:
    return [cid for cid in cell_ids if antigram.get_phenotype(cid).has(antigen)]


def _cells_not_carrying(antigram: Antigram, cell_ids: Sequence[str], antigen: str) -> List[str]:
    return [cid for cid in cell_ids if not antigram.get_phenotype(cid).has(antigen)]


def _exclusion_cells_single(
    antigram: Antigram, positive_cells: Sequence[str], antigen: str
) -> List[str]:
    """Cells carrying `antigen` that are NEGATIVE (informational rule-outs).

    A negative cell carrying the antigen contradicts the antibody's expected
    reactivity, so the antibody cannot be the cause.  Positive cells lacking
    the antigen are captured separately as 'single_exclusions' below.
    """
    exclusions = []
    neg_cells = get_negative_cells(antigram)
    for cid in neg_cells:
        if antigram.get_phenotype(cid).has(antigen):
            exclusions.append(cid)
    return exclusions


def identify_single(
    antigram: Antigram,
    candidates: Optional[Sequence[str]] = None,
) -> IdentificationResult:
    """Identify the best single-antibody explanation for the panel."""

    names = candidates or sorted(ANTIBODY_CATALOG.keys())
    positive_cells = get_positive_cells(antigram)
    negative_cells = get_negative_cells(antigram)
    auto_cells = get_auto_control_cells(antigram)

    result = IdentificationResult(patient_id=antigram.patient_id)

    if not positive_cells:
        result.flagged.append("no reactive cells; panel inconclusive")
        return result

    # Single antibody scoring: fraction of positive cells carrying the antigen.
    scores = {}
    exclusions = {}
    for name in names:
        antigen = next(iter(ANTIBODY_CATALOG[name]["antigens"]))
        carrying = _cells_carrying(antigram, positive_cells, antigen)
        score = len(carrying) / len(positive_cells)
        scores[name] = score
        exclusions[name] = _exclusion_cells_single(antigram, positive_cells, antigen)

    best_name = max(scores, key=scores.get)
    best_score = scores[best_name]
    best_exclusions = exclusions[best_name]

    result.single_score = best_score
    result.single_exclusions = best_exclusions

    # Auto-control check
    if auto_cells:
        # If any auto-control cell is positive, antibiotic single ID is
        # unreliable (autoantibody vs alloantibody).
        ac_positive = any(
            antigram.get_reaction(cid).is_positive(1) for cid in auto_cells
        )
        result.auto_control_positive = ac_positive
        if ac_positive:
            result.flagged.append(
                "auto control positive; result reflects possible autoantibody, "
                "methodist review required"
            )

    n_positive = len(positive_cells)
    # A single antibody is 'confident' when it explains all or nearly all
    # positive cells (>= 80%) AND there are enough informative negative cells.
    confident = (best_score >= 0.8) and (n_positive >= 2)

    result.confident_single = confident

    if confident:
        result.single_antibody = AntibodyCandidate(best_name)
    else:
        result.flagged.append(
            f"no single antibody explains the panel (best {best_name} covers "
            f"{best_score:.0%} of {n_positive} reactive cells)"
        )

    # Exclusions of the best candidate (all others ruled out by a negative
    # cell lacking their antigen, or by non-covering positive cells).
    ruled_out = [
        name for name in names
        if name != best_name and exclusions[name]
    ]
    result.single_exclusions = ruled_out

    return result


def _pair_valid(
    antigram: Antigram,
    cell_ids: Sequence[str],
    antigen_a: str,
    antigen_b: str,
) -> bool:
    """Check (A, B) together explains every reactive / non-reactive cell."""
    for cid in cell_ids:
        carries_a = antigram.get_phenotype(cid).has(antigen_a)
        carries_b = antigram.get_phenotype(cid).has(antigen_b)
        reaction = antigram.get_reaction(cid)
        if reaction.autocontrol:
            # Auto-control cells are relative; skip for pair validity.
            continue
        if is_reactive(reaction):
            if not (carries_a or carries_b):
                return False
        else:
            if carries_a or carries_b:
                return False
    return True


def identify_pairs(
    antigram: Antigram,
    candidates: Optional[Sequence[str]] = None,
) -> IdentificationResult:
    """Identify two-antibody combinations that jointly explain the panel."""

    names = candidates or sorted(ANTIBODY_CATALOG.keys())
    positive_cells = get_positive_cells(antigram)
    negative_cells = get_negative_cells(antigram)
    auto_cells = get_auto_control_cells(antigram)

    result = IdentificationResult(patient_id=antigram.patient_id)

    if not positive_cells:
        result.flagged.append("no reactive cells; no pair can be determined")
        return result

    pair_scores = {}
    valid_pairs = []

    # Ordered pair scan (A, B) with A < B alphabetically to avoid dupes.
    for i, name_a in enumerate(names):
        for name_b in names[i + 1:]:
            # Extract single antigen from each frozenset for validity checks.
            antigen_a = next(iter(ANTIBODY_CATALOG[name_a]["antigens"]))
            antigen_b = next(iter(ANTIBODY_CATALOG[name_b]["antigens"]))

            if not _pair_valid(antigram, positive_cells, antigen_a, antigen_b):
                continue
            if not _pair_valid(antigram, negative_cells, antigen_a, antigen_b):
                continue

            # Score = fraction of positive cells covered by A or B.
            # Require each antibody to support at least one reactive cell
            # (else the pair is clinically meaningless, e.g. anti-A1 + anti-K
            # on a pure anti-K panel).
            covering_a = set(
                _cells_carrying(antigram, positive_cells, antigen_a)
            )
            covering_b = set(
                _cells_carrying(antigram, positive_cells, antigen_b)
            )
            if not covering_a or not covering_b:
                continue

            covered = covering_a | covering_b
            # Deduplicate (cells carrying both).
            covered_set = set(covered)
            score = len(covered_set) / len(positive_cells)
            pair_scores[(name_a, name_b)] = score
            valid_pairs.append((name_a, name_b))

    if not valid_pairs:
        result.flagged.append("no two-antibody combination explains the panel")
        return result

    # Sort by score descending.
    sorted_pairs = sorted(valid_pairs, key=lambda p: pair_scores[p], reverse=True)
    result.pairs = sorted_pairs
    result.pair_scores = [pair_scores[p] for p in sorted_pairs]

    # A pair is confident when it explains >= 80% of positive cells.
    top_pair = sorted_pairs[0]
    top_score = pair_scores[top_pair]
    result.confident_pairs = [top_pair] if top_score >= 0.8 else []

    if result.confident_pairs:
        result.single_antibody = AntibodyCandidate(top_pair[0])
        result.confident_single = True
    else:
        result.flagged.append(
            f"single antibody insufficient; consider {', '.join(top_pair)} "
            f"(covers {top_score:.0%} of positive cells)"
        )

    return result


def identify(antigram: Antigram, candidates: Optional[Sequence[str]] = None) -> IdentificationResult:
    """Run single- and pair-identification over an antigram."""

    result = identify_single(antigram, candidates)
    pairs_result = identify_pairs(antigram, candidates)

    # Merge pairs into the single result.
    result.pairs = pairs_result.pairs
    result.confident_pairs = pairs_result.confident_pairs
    result.pair_scores = pairs_result.pair_scores
    result.auto_control_positive = (
        result.auto_control_positive or pairs_result.auto_control_positive
    )
    result.flagged.extend(pairs_result.flagged)

    return result
