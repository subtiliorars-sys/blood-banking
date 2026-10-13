"""abid — antibody identification engine for blood banking.

Built on reference material and standard RBC antibody identification exclusion
logic as described in the 12th edition of Dacie & Lewis, Practical Haematology.
"""

from .antigram import Antigram, CellPhenotype, CellReaction
from .antibody import AntibodyCandidate, ANTIBODY_CATALOG
from .rules import (
    IdentificationResult,
    get_auto_control_cells,
    get_negative_cells,
    get_positive_cells,
    identify,
    identify_pairs,
    identify_single,
    is_reactive,
)
from .version import __version__

__all__ = [
    "Antigen",
    "Antigram",
    "CellPhenotype",
    "CellReaction",
    "AntibodyCandidate",
    "ANTIBODY_CATALOG",
    "IdentificationResult",
    "get_auto_control_cells",
    "get_negative_cells",
    "get_positive_cells",
    "identify",
    "identify_pairs",
    "identify_single",
    "is_reactive",
    "__version__",
]
