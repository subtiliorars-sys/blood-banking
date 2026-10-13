"""Test panels for the antibody identification engine."""

import pytest

from abid.antigram import Antigram, CellPhenotype, CellReaction
from abid.rules import (
    identify,
    identify_pairs,
    identify_single,
    get_auto_control_cells,
    get_negative_cells,
    get_positive_cells,
)


def make_antigram(
    patient_id: str,
    serum: str,
    cells: dict,
    reactions: dict,
    auto_control_cells: list = None,
) -> Antigram:
    cells = {cid: CellPhenotype(cid, antigens=frozenset(ants)) for cid, ants in cells.items()}
    ac = auto_control_cells or []
    reactions = {
        cid: CellReaction(cid, grade=g, autocontrol=(cid in ac))
        for cid, g in reactions.items()
    }
    return Antigram(patient_id=patient_id, serum=serum, cells=cells, reactions=reactions)


# ---- anti-K single antibody (5 cells: 5 reactive, all K+) ----


def make_anti_K_panel():
    cells = {
        "C1": {"K"},
        "C2": {"K"},
        "C3": {"K"},
        "C4": {"K"},
        "C5": {"K"},
    }
    reactions = {
        "C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3,
    }
    return make_antigram("PT-K1", "serum-A", cells, reactions)


# ---- anti-E single antibody (4 cells) ----


def make_anti_E_panel():
    cells = {
        "C1": {"E"},
        "C2": {"E"},
        "C3": {"E"},
        "C4": {"E"},
    }
    reactions = {"C1": 2, "C2": 3, "C3": 2, "C4": 2}
    return make_antigram("PT-E1", "serum-B", cells, reactions)


# ---- anti-e single antibody ----


def make_anti_e_panel():
    cells = {
        "C1": {"e"},
        "C2": {"e"},
        "C3": {"e"},
        "C4": {"e", "E"},  # e+ E+
    }
    reactions = {"C1": 3, "C2": 2, "C3": 3, "C4": 2}
    return make_antigram("PT-e1", "serum-C", cells, reactions)


# ---- two-antibody: anti-E + anti-K ----


def make_E_K_panel():
    cells = {
        "C1": {"E", "K"},
        "C2": {"E", "K"},
        "C3": {"E", "K"},
        "C4": {"E", "K"},
        "C5": {"E", "K"},
        "C6": {"E"},      # E+, K-
        "C7": {"K"},      # E-, K+
        "C8": {"e", "k"}, # double negative
    }
    reactions = {
        "C1": 3, "C2": 3, "C3": 3, "C4": 3, "C5": 3,
        "C6": 2, "C7": 2, "C8": 0,
    }
    return make_antigram("PT-E+K", "serum-D", cells, reactions)


# ---- auto-control positive panel (ambiguous, tests flagging) ----


def make_auto_control_panel():
    cells = {
        "C1": {"K"},
        "C2": {"K"},
        "C3": {"D"},   # auto control
        "C4": {"k"},
        "C5": {"e"},
    }
    reactions = {
        "C1": 3, "C2": 3,
        "C3": 3,  # auto control positive
        "C4": 1, "C5": 1,
    }
    return make_antigram("PT-AC1", "serum-X", cells, reactions, auto_control_cells=["C3"])


# ---- negative / inconclusive panel ----


def make_negative_panel():
    cells = {
        "C1": {"K"},
        "C2": {"E"},
        "C3": {"k"},
        "C4": {"e"},
    }
    reactions = {"C1": 0, "C2": 0, "C3": 0, "C4": 0}
    return make_antigram("PT-NEG", "serum-Z", cells, reactions)


# =====================================================================
#	Assertions
# =====================================================================


def test_positive_cells():
    a = make_anti_K_panel()
    assert get_positive_cells(a) == ["C1", "C2", "C3", "C4", "C5"]


def test_negative_cells_are_negative():
    a = make_anti_K_panel()
    neg = get_negative_cells(a)
    assert not neg


def test_auto_control_cells():
    a = make_auto_control_panel()
    assert get_auto_control_cells(a) == ["C3"]


def test_single_anti_K_confident():
    res = identify_single(make_anti_K_panel())
    assert res.confident_single is True
    assert res.single_antibody.name == "anti-K"
    assert res.single_score == 1.0
    # Nothing else explained: all others ruled out by non-K positive cells? no.
    # A cell carrying K but negative would rule out anti-K... none here.
    # But anti-k is constant negative - ruled out by negative cells carrying k? none.
    # Only cells all carry K; so others have no positive cells carrying them.
    # So single_exclusions == [].
    assert res.single_exclusions == []


def test_single_anti_E_confident():
    res = identify_single(make_anti_E_panel())
    assert res.confident_single is True
    assert res.single_antibody.name == "anti-E"
    assert res.single_score == 1.0


def test_single_anti_e_confident():
    res = identify_single(make_anti_e_panel())
    # C1( e ), C2( e ), C3( e ), C4( e+E )
    # All 4 positive cells carry e; C4 also carries E.
    assert res.confident_single is True
    assert res.single_antibody.name == "anti-e"


def test_single_auto_control_flagged():
    res = identify_single(make_auto_control_panel())
    assert res.auto_control_positive is True
    assert any("auto control" in f for f in res.flagged)


def test_single_negative_inconclusive():
    res = identify_single(make_negative_panel())
    assert res.confident_single is False
    assert any("no reactive cells" in f for f in res.flagged)


# =====================================================================
#	Pair identification
# =====================================================================


def test_pairs_E_K():
    res = identify_pairs(make_E_K_panel())
    assert res.confident_pairs, res.to_dict()
    pair = res.confident_pairs[0]
    assert set(pair) == {"anti-E", "anti-K"}
    assert res.pair_scores[0] == 1.0


def test_pairs_out_of_order():
    res = identify_pairs(make_E_K_panel())
    pair = res.pairs[0]
    components = set(pair)
    assert components == {"anti-E", "anti-K"}


def test_pair_anti_E_plus_anti_K_not_confident():
    # E covers 6/7 cells, K covers 6/7 cells, but NEITHER single antibody
    # explains all positives on its own. E+K together explains 7/7 => confident.
    res = identify_single(make_E_K_panel())
    assert res.confident_single is True
    assert res.single_antibody.name in ("anti-E", "anti-K")
    assert res.single_score < 1.0
    # pair works and is confident at 1.0
    pair_res = identify_pairs(make_E_K_panel())
    assert pair_res.confident_pairs == [("anti-E", "anti-K")]
    assert pair_res.pair_scores[0] == 1.0


# =====================================================================
#	Top-level identify()
# =====================================================================


def test_identify_single_anti_K():
    res = identify(make_anti_K_panel())
    assert res.confident_single is True
    assert res.single_antibody.name == "anti-K"


def test_identify_pairs_E_K():
    res = identify(make_E_K_panel())
    assert res.confident_pairs, res.to_dict()
    assert {"anti-E", "anti-K"} == set(res.confident_pairs[0])


def test_identify_auto_control_flag():
    res = identify(make_auto_control_panel())
    assert res.auto_control_positive is True
    assert res.confident_single is False  # no single explains


def test_identify_negative():
    res = identify(make_negative_panel())
    assert res.confident_single is False
    assert res.confident_pairs == []


if __name__ == "__main__":
    pytest.main([__file__])
