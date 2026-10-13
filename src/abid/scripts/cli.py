#!/usr/bin/env python3
"""CLI for the abid antibody identification engine.

The engine emits a JSON envelope to stdout and human-readable text to
stderr.  The frontend reads stdout (machine readable) and stderr (diagnostics).

Envelope schema:
{
  "patient_id": str,
  "serum": str,
  "single_antibody": str | null,
  "confident_single": bool,
  "single_score": float,
  "single_exclusions": [str],
  "pairs": [[str, str], ...],
  "pair_scores": [float, ...],
  "pair_status": ["confident" | "review", ...],
  "auto_control_positive": bool,
  "flagged": [str],
  "identity": [
    {"cell_id": str, "phenotype": str, "grade": int,
     "status": "positive" | "negative" | "auto"}
  ]
}
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


def build_envelope(antigram: Antigram, result) -> dict:
    identity_rows = []
    for cid in sorted(antigram.cells.keys()):
        r = antigram.get_reaction(cid)
        grade = r.grade
        if r.autocontrol:
            status = "auto"
        else:
            status = "positive" if grade >= 1 else "negative"
        identity_rows.append({
            "cell_id": cid,
            "phenotype": ", ".join(sorted(antigram.get_phenotype(cid).antigens)),
            "grade": grade,
            "status": status,
        })

    pairs_with_status = []
    pair_scores = []
    pair_status = []
    for (a, b), score in zip(result.pairs, result.pair_scores):
        pairs_with_status.append([a, b])
        pair_scores.append(float(score))
        pair_status.append("confident" if score >= 0.8 else "review")

    return {
        "patient_id": antigram.patient_id,
        "serum": antigram.serum,
        "single_antibody": result.single_antibody.name if result.single_antibody else None,
        "confident_single": bool(result.confident_single),
        "single_score": round(float(result.single_score), 4),
        "single_exclusions": list(result.single_exclusions),
        "pairs": pairs_with_status,
        "pair_scores": [round(float(s), 4) for s in pair_scores],
        "pair_status": pair_status,
        "auto_control_positive": bool(result.auto_control_positive),
        "flagged": list(result.flagged),
        "identity": identity_rows,
        "dev": {"engine": "abid", "version": __version__},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Antibody identification (abid) - blood banking panel analysis"
    )
    parser.add_argument(
        "--version", action="version", version=f"abid {__version__}"
    )
    parser.add_argument(
        "--patient", "-p", help="Patient ID (optional if JSON provides it)"
    )
    parser.add_argument(
        "--antigram", "-a", type=Path, help="Path to antigram JSON"
    )
    parser.add_argument(
        "--json", action="store_true", help="Print JSON envelope to stdout"
    )
    parser.add_argument(
        "input", nargs="?", default=None,
        help="Path to JSON panel. If omitted, the JSON panel is read from stdin.",
    )
    args = parser.parse_args(argv)

    try:
        if args.antigram:
            antigram = load_antigram(args.antigram)
        else:
            # Read JSON panel from stdin, or from a positional path.
            if args.input is None or args.input == "-":
                raw = sys.stdin.read()
            else:
                raw = Path(args.input).read_text(encoding="utf-8")
            data = json.loads(raw)
            cells = {
                cid: CellPhenotype(cid, antigens=frozenset(v))
                for cid, v in data.get("cells", {}).items()
            }
            reactions = {
                cid: CellReaction(cid, grade=int(r.get("grade", 0)), autocontrol=bool(r.get("autocontrol")))
                for cid, r in data.get("reactions", {}).items()
            }
            antigram = Antigram(
                patient_id=data.get("patient_id", args.patient or "unknown"),
                serum=data.get("serum", args.patient or "serum"),
                cells=cells,
                reactions=reactions,
                comments=data.get("comments", []),
            )
    except Exception as exc:
        print(f"error: could not load antigram: {exc}", file=sys.stderr)
        return 2

    result = identify(antigram)

    if args.json:
        print(json.dumps(build_envelope(antigram, result), indent=2))
    else:
        print(f"Patient: {antigram.patient_id}")
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
