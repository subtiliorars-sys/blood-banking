#!/usr/bin/env python3
"""CLI for the abid antibody identification engine.

Example:
    python -m abid.scripts.cli --patient PT-001 --antigram samples/antigram_k.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from abid import __version__
from abid.antigram import Antigram, CellPhenotype, CellReaction
from abid.rules import identify


def load_antigram(path: Path) -> Antigram:
    data = json.loads(path.read_text(encoding="utf-8"))
    cells = {
        cid: CellPhenotype(cid, antigens=frozenset(data["cells"].get(cid, [])))
        for cid in data["cells"]
    }
    reactions = {
        cid: CellReaction(cid, grade=int(r.get("grade", 0)), autocontrol=bool(r.get("autocontrol")))
        for cid, r in data.get("reactions", {}).items()
    }
    return Antigram(
        patient_id=data.get("patient_id", "unknown"),
        serum=data.get("serum", "serum"),
        cells=cells,
        reactions=reactions,
        comments=data.get("comments", []),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Antibody identification (abid) - blood banking panel analysis"
    )
    parser.add_argument("--version", action="version", version=f"abid {__version__}")
    parser.add_argument(
        "--patient", "-p", required=True, help="Patient ID for the report"
    )
    parser.add_argument(
        "--antigram",
        "-a",
        type=Path,
        required=True,
        help="Path to antigram JSON (see samples/antigram_k.json)",
    )
    args = parser.parse_args(argv)

    try:
        antigram = load_antigram(args.antigram)
    except Exception as exc:
        print(f"error: could not load antigram {args.antigram}: {exc}", file=sys.stderr)
        return 2

    result = identify(antigram)

    print(f"Patient: {result.patient_id}")
    print("-" * 60)
    print(f"Single antibody: {result.single_antibody.name if result.single_antibody else 'none'}")
    print(f"Confident single: {result.confident_single}")
    print(f"Single score: {result.single_score:.3f}")
    if result.single_exclusions:
        print(f"Single exclusions: {', '.join(result.single_exclusions)}")
    if result.pairs:
        print("Two-antibody candidates:")
        for pair, score in zip(result.pairs, result.pair_scores):
            print(f"  {pair[0]} + {pair[1]}  (score {score:.3f})")
            if pair in result.confident_pairs:
                print(f"    -> CONFIDENT")
    if result.auto_control_positive:
        print("WARNING: auto control positive - possible autoantibody")
    if result.flagged:
        print("Flagged:")
        for f in result.flagged:
            print(f"  - {f}")
    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"  - {w}")
    if not result.pairs and not result.flagged:
        print("No antibodies identified; panel is inconclusive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
