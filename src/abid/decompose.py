"""Two-antibody decomposition tooling.

The identification engine can return a pair of antibodies (A + B) whose combined
coverage explains the reactive panel, but the split is not always unambiguous.

This module turns a pair-classified (or single) case into concrete, ordered
action suggestions a technologist can execute so the second antibody is no
longer guessed.

Relationship to the results ledger
----------------------------------
Each analysis is persisted in the SQLite ledger (see app.console).  The
decomposition engine is called on the *stored envelope*; it never stores new
state on its own.  Its output is a plain list of structs that the engine
reports display and that the AABB/CAP audit export can include as a second step.

Suggestion types
----------------
- prozone     - very strong 4+ reactions that "read" as critical but are due
                to antibody excess (the prozone effect).  Suggest serial saline
                dilution to bring the reaction into the zone.
- enhancement - many antigen-antibody reactions are too weak to agglutinate in
                saline; suggest LIS (low-ionic-strength solution) / ISAGENIX,
                and optionally a 37C incubation panel.  Often unmasks the
                second antibody.
- adsorption  - remove the suspected antibody by panel adsorption (monoclonal /
                isoantibody) then re-run.  This is the definitive way to split
                a two-antibody case when cell typing is clean and both
                antibodies are well-characterised.
- eager       - polyspecific globulin / ready-slide "eager" method, or a
                direct-antiglobulin test (DAT) to pick up unexpected strong
                reactions.
- followup    - whenever auto-control is positive, decomposition is replaced by
                an anti-human globulin (warm AIHA) workup; we never suggest
                prozone/enhancement in that setting.

All suggestions are idempotent and auditable: the technician can mark each as
`not_run`, `in_progress`, `completed`, and record an outcome, which the ledger
captures as an optional step table.

Evidence model
--------------
Each identity row is a dict with at least:
  cell_id      : str
  phenotype    : str (e.g. "E, K", "E", or ["E","K"])
  grade        : int (0 = negative)
  status       : "positive" | "negative" | "auto"
Optional:
  autocontrol  : bool
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Unused; the decomposition engine only needs cell_id, phenotype, grade, status.
@dataclass(frozen=True)
class DecompositionSuggestion:
    suggestion_type: str  # prozone | enhancement | adsorption | eager | followup
    title: str
    why: str
    action: str
    cells: list[str] = field(default_factory=list)
    expected: str = ""
    priority: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def type(self) -> str:
        return self.suggestion_type


def _positive_cells(evidence: list[dict]) -> list[str]:
    return [r["cell_id"] for r in evidence if r.get("status") == "positive"]


def _negative_cells(evidence: list[dict]) -> list[str]:
    return [
        r["cell_id"]
        for r in evidence
        if r.get("status") in ("negative", "auto") and not r.get("autocontrol", False)
    ]


def _cell_grades(evidence: list[dict]) -> dict[str, int]:
    return {r["cell_id"]: int(r.get("grade", 0)) for r in evidence}


def _cells_above(grades: dict[str, int], threshold: int) -> list[str]:
    return sorted([cid for cid, g in grades.items() if g >= threshold])


def _phenotype_tokens(phenotype: Any) -> set[str]:
    """Normalise a phenotype field to a set of antigen tokens."""
    if phenotype is None:
        return set()
    if isinstance(phenotype, (list, tuple, set)):
        return {str(x).strip().upper() for x in phenotype}
    text = str(phenotype).strip()
    if not text:
        return set()
    # "E, K" -> ["E", "K"]
    return {p.strip().upper() for p in text.replace(";", ",").split(",") if p.strip()}


def _cells_carrying(evidence: list[dict], antigen_names: Iterable[str]) -> list[str]:
    """Cells that are positive and carry at least one of `antigen_names`."""
    wanted = {str(a).strip().upper() for a in antigen_names}
    out = []
    for r in evidence:
        if r.get("status") == "positive" and _phenotype_tokens(r.get("phenotype")) & wanted:
            out.append(r["cell_id"])
    return out


def suggest_decomposition(
    evidence: list[dict],
    identified: dict[str, Any],
    prior_pair: Optional[list[str]] = None,
) -> list[DecompositionSuggestion]:
    """Rank decomposition suggestions for a pair-classified or single case.

    `prior_pair` is the (A, B) the engine thinks best explains the panel when
    the result is a pair-classified 'review' — e.g. ['anti-E', 'anti-K'].
    """
    suggestions: list[DecompositionSuggestion] = []

    # 1. Auto-control positive replaces decomposition with an AIHA work-up.
    ac_positive = bool(
        identified.get("auto_control_positive")
        or any(e.get("autocontrol") for e in evidence)
    )
    if ac_positive:
        suggestions.append(
            DecompositionSuggestion(
                suggestion_type="followup",
                title="Auto-control positive — work up for warm autoimmune hemolytic anemia",
                why=(
                    "The auto-control is positive.  This rules out a routine "
                    "two-antibody alloantibody decomposition; the reactivity is "
                    "consistent with a warm autoantibody or a high-titer cold "
                    "agglutinin that cross-reacts."
                ),
                action=(
                    "Stop decomposition. Run a DAT (direct antiglobulin test), "
                    "warm autoantibody elution, and an IgG-subclass/adsorption "
                    "panel.  Do not interpret prozone or enhancement in this "
                    "setting."
                ),
                priority=0,
                notes=[
                    "Autoantibodies mask alloantibody splits.",
                    "A specificity from the envelope may represent a broad IgG "
                    "reactivity; treat the reported single as a lead, not proof.",
                ],
            )
        )
        return suggestions

    if not identified.get("pairs") or len(identified["pairs"]) == 0:
        return suggestions

    prior_pair = prior_pair or []
    pair = identified["pairs"][0] if identified["pairs"] else []
    pair_set = set(pair) if pair else set()

    # --- 1. PROBE strong cells: prozone --------------------------------
    grades = _cell_grades(evidence)
    high = _cells_above(grades, 3)
    if high and len(high) >= 2:
        pair_cells = set(_cells_carrying(evidence, pair_set))
        if pair_cells and pair_cells & set(high):
            suggestions.append(
                DecompositionSuggestion(
                    suggestion_type="prozone",
                    title="Prozone reaction suspected (antibody excess)",
                    why=(
                        f"{len(high)} cells at grade 4+ ({high}) is the textbook "
                        "prozone picture: the strongest reactions are weaker than "
                        "expected because antibody excess suppresses agglutination."
                    ),
                    action=(
                        "Serial saline dilution (prozone curve): 1:2, 1:4, 1:8, "
                        "1:16, 1:32, 1:64, 1:128 in LIS. Re-run the panel at "
                        "each dilution; the reaction re-appears as you enter "
                        "the zone, frequently revealing the second antibody."
                    ),
                    cells=high,
                    expected=(
                        "A prozone curve shows the 4+ unmasking to 2-3+; the "
                        "second antibody is then identified by single-cell ID "
                        "at dilution rather than at the undiluted point."
                    ),
                    priority=2,
                )
            )

    # --- 2. WEAK reactions: enhancement ------------------------
    weak = [cid for cid in _cells_above(grades, 1) if grades[cid] == 1]
    if weak:
        suggestions.append(
            DecompositionSuggestion(
                suggestion_type="enhancement",
                title="Weak reactions — enhance the panel",
                why=(
                    "Reactive cells at grade 1+ are often under-read in saline. "
                    "LIS (low-ionic-strength solution) or 37C incubation "
                    "typically raises them to 2-3+, which can unmask the second "
                    "antibody."
                ),
                action=(
                    "Re-run the panel in LIS at 37C for 15-30 min with a "
                    "monoclonal/polyspecific IAT, or perform a 37C LIS panel. "
                    "Compare against the saline panel you entered."
                ),
                cells=weak,
                priority=3,
            )
        )

    # --- 3. DEFINITE split: adsorption ------------------------
    if len(prior_pair) >= 2:
        part_a = _cells_carrying(evidence, {prior_pair[0]})
        part_b = _cells_carrying(evidence, {prior_pair[1]})
        if part_a and part_b and len(part_a) >= 2 and len(part_b) >= 2:
            suggestions.append(
                DecompositionSuggestion(
                    suggestion_type="adsorption",
                    title="Adsorption (definitive two-antibody split)",
                    why=(
                        "The pair (A + B) is the best fit, but neither the strong "
                        "nor weak cell set cleanly separates the two antibodies "
                        "for a confidence call. Adsorption is the only way to "
                        "split a two-antibody case when the panel cells are "
                        "clean and both antibodies are well-characterised."
                    ),
                    action=(
                        "Adsorb the patient's plasma against group O pack red "
                        "cells typed for the first antibody only (e.g. K-K- for anti-K). The supernatant is then "
                        "revisited against the original panel: the surviving "
                        "reactivity is the second antibody (B). Repeat with "
                        "the reciprocal adsorption if needed."
                    ),
                    cells=sorted(set(part_a) | set(part_b)),
                    priority=1,
                    notes=[
                        "Confirm cell typing for the first antibody is correct "
                        "before adsorbing.",
                        "Document the adsorbing cells' phenotype in the report.",
                    ],
                )
            )

    # --- 4. CROSS-POINTING / EAGER --------------------------------
    if not suggestions:
        suggestions.append(
            DecompositionSuggestion(
                suggestion_type="eager",
                title="Eager / polyspecific method and DAT",
                why=(
                    "A second antibody is often first suspected when a reaction "
                    "that should be exactly matched is stronger in a mixed-cell "
                    "or polyspecific system.  The eager method and a DAT can "
                    "expose unexpected strong reactivity saline panels miss."
                ),
                action=(
                    "Run a 3-cell 'eager' slide (automatic polyspecific or "
                    "monoclonal IAT) and a DAT. Compare with the saline panel "
                    "you entered."
                ),
                priority=4,
            )
        )

    suggestions.sort(key=lambda s: s.priority)
    return suggestions
