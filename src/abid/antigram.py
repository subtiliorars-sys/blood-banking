"""Antigram: patient antibody panel data model.

An antigram records, for each panel/donor red cell tested, which test cells
reacted (graded) and their known antigen phenotypes (e.g. D, C, c, E, e, K, k,
Fy(a), Fy(b), Jk(a), Jk(b), ...).

This is the raw input; deliberately framework-agnostic so it can be produced by
any laboratory instrument export and consumed by the identification engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, FrozenSet


@dataclass(frozen=True)
class CellPhenotype:
    """Phenotype of one test red blood cell."""

    cell_id: str
    antigens: FrozenSet[str] = field(default_factory=frozenset)

    def has(self, antigen: str) -> bool:
        return antigen in self.antigens


@dataclass(frozen=True)
class CellReaction:
    """Reaction grade for one test cell."""

    cell_id: str
    grade: int  # 0 = negative, 1-5 approximate, 4+ typically strongest
    autocontrol: bool = False  # True if this cell's plasma was the patient's own

    def is_positive(self, threshold: int = 1) -> bool:
        return self.grade >= threshold


@dataclass(frozen=True)
class Antigram:
    """Complete antibody panel record for one patient."""

    patient_id: str
    serum: str  # which patient serum/plasma was tested
    cells: Dict[str, CellPhenotype] = field(default_factory=dict)
    reactions: Dict[str, CellReaction] = field(default_factory=dict)
    comments: List[str] = field(default_factory=list)

    def cell_ids(self) -> List[str]:
        return sorted(self.cells.keys())

    def get_phenotype(self, cell_id: str) -> CellPhenotype:
        return self.cells[cell_id]

    def get_reaction(self, cell_id: str) -> CellReaction:
        return self.reactions[cell_id]

    def is_positive(self, cell_id: str, threshold: int = 1) -> bool:
        return self.get_reaction(cell_id).is_positive(threshold)

    def get_phenotype_iter(self):
        """Iterate (cell_id, phenotype) pairs for convenience."""
        return self.cells.items()

    def get_reaction_iter(self):
        return self.reactions.items()
