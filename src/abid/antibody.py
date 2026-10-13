"""Candidate antibody model.

Recognizes the most commonly reported clinically significant RBC antibodies.
Each antibody carries: its typical direct-agglutination grades, the
exclusion rules it is subject to (e.g. auto control, mixed-field, subgroup
variation), and heuristics used by the identification engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, List, Optional


# A small curated catalog. Expand as needed.
ANTIBODY_CATALOG = {
    "anti-D": {
        "name": "Anti-D",
        "frequency": "common (in D- recipients of D+ blood)",
        "typical_grade": 3,
        "antigens": frozenset({"D"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": False,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-C": {
        "name": "Anti-C",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"C"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-c": {
        "name": "Anti-c",
        "frequency": "common",
        "typical_grade": 3,
        "antigens": frozenset({"c"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-E": {
        "name": "Anti-E",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"E"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-e": {
        "name": "Anti-e",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"e"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-K": {
        "name": "Anti-K",
        "frequency": "common",
        "typical_grade": 3,
        "antigens": frozenset({"K"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": False,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-k": {
        "name": "Anti-k",
        "frequency": "common",
        "typical_grade": 3,
        "antigens": frozenset({"k"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": False,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-Fya": {
        "name": "Anti-Fya",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"Fya"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-Fyb": {
        "name": "Anti-Fyb",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"Fyb"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-Jka": {
        "name": "Anti-Jka",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"Jka"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-Jkb": {
        "name": "Anti-Jkb",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"Jkb"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-S": {
        "name": "Anti-S",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"S"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-s": {
        "name": "Anti-s",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"s"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-M": {
        "name": "Anti-M",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"M"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-N": {
        "name": "Anti-N",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"N"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-Lua": {
        "name": "Anti-Lua",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"Lua"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-Leb": {
        "name": "Anti-Leb",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"Leb"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-P1": {
        "name": "Anti-P1",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"P1"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-Lea": {
        "name": "Anti-Lea",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"Lea"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-A1": {
        "name": "Anti-A1",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"A1"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-B": {
        "name": "Anti-B",
        "frequency": "common",
        "typical_grade": 2,
        "antigens": frozenset({"B"}),
        "auto_control": False,
        "mixed_field": False,
        "subgroup_variation": True,
        "heat_labile": True,
        "gravlial": False,
    },
    "anti-Jra": {
        "name": "Anti-Jra",
        "frequency": "rare",
        "typical_grade": 2,
        "antigens": frozenset({"Jra"}),
        "auto_control": False,
        "mixed_field": True,
        "subgroup_variation": False,
        "heat_labile": False,
        "gravlial": False,
    },
    "anti-Wra": {
        "name": "Anti-Wra",
        "frequency": "rare",
        "typical_grade": 2,
        "antigens": frozenset({"Wra"}),
        "auto_control": False,
        "mixed_field": True,
        "subgroup_variation": False,
        "heat_labile": False,
        "gravlial": False,
    },
}


@dataclass(frozen=True)
class AntibodyCandidate:
    """A candidate antibody the identification engine considers."""

    name: str
    catalog: dict = None

    def __post_init__(self):
        if self.catalog is None:
            object.__setattr__(self, "catalog", ANTIBODY_CATALOG[self.name])

    @property
    def antigens(self) -> FrozenSet[str]:
        return self.catalog["antigens"]

    @property
    def auto_control(self) -> bool:
        return self.catalog["auto_control"]

    @property
    def mixed_field(self) -> bool:
        return self.catalog["mixed_field"]

    @property
    def subgroup_variation(self) -> bool:
        return self.catalog["subgroup_variation"]

    def is_reactive(self, cell_id: str, grade: int) -> bool:
        """Heuristic: does a given cell reaction plausibly belong to this antibody?"""
        return grade >= 1
