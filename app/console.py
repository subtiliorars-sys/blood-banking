#!/usr/bin/env python3
"""Console launcher for the Blood Banking Antibody ID frontend.

Serving the static UI (index.html, styles.css, main.js) and exposing a small
HTTP API that runs the `abid` engine, persists each analysis to SQLite, and
drives the two-antibody decomposition suggestions.

Endpoints:
  GET  /                     -> index.html
  GET  /<path:path>          -> static assets
  POST /api/analyze          -> {payload: str, entered_by: str}  -> analysis
  GET  /api/history          -> recent panels
  GET  /api/history/<id>     -> one panel + envelope + decomposition
  GET  /healthz              -> health check

Run:
    python console.py                 # serve on 0.0.0.0:9120
    python console.py --host 127.0.0.1 --port 9120
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, request, send_from_directory

# Resolve the abid package (setuptools editable install vs source tree).
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.exists():
    sys.path.insert(0, str(_SRC))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
elif str(Path(__file__).resolve().parent.parent.parent / "src").exists():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from abid import __version__
from abid.antigram import Antigram, CellPhenotype, CellReaction
from abid.decompose import suggest_decomposition
from abid.persistence import Ledger, canonical_payload, sha256
from abid.rules import identify
from abid import export as abid_export

BASE_DIR = Path(__file__).resolve().parent.parent
UI_DIR = BASE_DIR / "app" / "build" / "win" / "dist"
DEFAULT_DB = BASE_DIR / "data" / "panels.db"
DEFAULT_PORT = 9120


def panel_to_antigram(raw: dict[str, Any]) -> Antigram:
    cells = {
        cid: CellPhenotype(cid, frozenset(ants))
        for cid, ants in raw.get("cells", {}).items()
    }
    reactions = {
        cid: CellReaction(cid, grade=int(r.get("grade", 0)), autocontrol=bool(r.get("autocontrol")))
        for cid, r in raw.get("reactions", {}).items()
    }
    return Antigram(
        patient_id=raw.get("patient_id", "unknown"),
        serum=raw.get("serum", "serum"),
        cells=cells,
        reactions=reactions,
        comments=raw.get("comments", []),
    )


def run_engine(raw: dict[str, Any], patient_id: str, serum: str) -> dict[str, Any]:
    ant = panel_to_antigram(raw)
    result = identify(ant)
    env = {
        "patient_id": ant.patient_id,
        "serum": ant.serum,
        "single_antibody": result.single_antibody.name if result.single_antibody else None,
        "confident_single": bool(result.confident_single),
        "single_score": round(float(result.single_score), 4),
        "single_exclusions": list(result.single_exclusions),
        "pairs": [list(p) for p in result.pairs],
        "pair_scores": [round(float(s), 4) for s in result.pair_scores],
        "pair_status": ["confident" if s >= 0.8 else "review" for s in result.pair_scores],
        "auto_control_positive": bool(result.auto_control_positive),
        "flagged": list(result.flagged),
        "identity": [
            {
                "cell_id": cid,
                "phenotype": ", ".join(sorted(ant.get_phenotype(cid).antigens)),
                "grade": r.grade,
                "status": "positive" if r.grade >= 1 and not r.autocontrol else (
                    "auto" if r.autocontrol else "negative"
                ),
            }
            for cid, r in ant.reactions.items()
        ],
        "dev": {"engine": "abid", "version": __version__},
    }
    # Decomp suggestions run on the stored envelope.
    env["decomp"] = suggest_decomposition(env["identity"], env, prior_pair=result.pairs[0] if result.pairs else None)
    return env


def build_app(db: Path) -> tuple[Flask, Ledger]:
    app = Flask(
        __name__,
        static_folder=str(UI_DIR / "styles"),
        static_url_path="/styles",
    )
    ledger = Ledger(db)

    @app.get("/")
    def index():
        return send_from_directory(UI_DIR, "index.html")

    @app.get("/<path:path>")
    def static_file(path: str):
        return send_from_directory(UI_DIR, path)

    @app.post("/api/analyze")
    def api_analyze():
        data = request.get_json(silent=True) or {}
        payload = data.get("payload", "")
        entered_by = data.get("entered_by", "unknown")
        try:
            raw = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return jsonify({"error": "invalid JSON payload"}), 400

        patient_id = raw.get("patient_id", "unknown")
        serum = raw.get("serum", "serum")
        try:
            ant = panel_to_antigram(raw)
            result = identify(ant)
            identity = [
                {
                    "cell_id": cid,
                    "phenotype": ", ".join(sorted(ant.get_phenotype(cid).antigens)),
                    "grade": r.grade,
                    "status": "positive" if r.grade >= 1 and not r.autocontrol else (
                        "auto" if r.autocontrol else "negative"
                    ),
                }
                for cid, r in ant.reactions.items()
            ]
            pairs = [list(p) for p in result.pairs]
            pair_scores = [round(float(s), 4) for s in result.pair_scores]
            decomp = suggest_decomposition(
                identity,
                {
                    "patient_id": ant.patient_id,
                    "serum": ant.serum,
                    "pairs": pairs,
                    "pair_scores": pair_scores,
                    "pair_status": ["confident" if s >= 0.8 else "review" for s in pair_scores],
                    "identity": identity,
                },
                prior_pair=result.pairs[0] if result.pairs else None,
            )
            env = {
                "patient_id": ant.patient_id,
                "serum": ant.serum,
                "single_antibody": result.single_antibody.name if result.single_antibody else None,
                "confident_single": bool(result.confident_single),
                "single_score": round(float(result.single_score), 4),
                "single_exclusions": list(result.single_exclusions),
                "pairs": pairs,
                "pair_scores": pair_scores,
                "pair_status": ["confident" if s >= 0.8 else "review" for s in pair_scores],
                "auto_control_positive": bool(result.auto_control_positive),
                "flagged": list(result.flagged),
                "identity": identity,
                "decomp": [
                    {
                        "suggestion_type": s.suggestion_type,
                        "title": s.title,
                        "why": s.why,
                        "action": s.action,
                        "cells": list(s.cells),
                        "expected": s.expected,
                        "priority": s.priority,
                        "notes": list(s.notes),
                    }
                    for s in decomp
                ],
            }
            deidentified_id = ledger.save(raw, env, entered_by=entered_by)
            env["deidentified_id"] = deidentified_id
            return jsonify({
                "deidentified_id": deidentified_id,
                "analysis": env,
                "ok": True,
            })
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500

    @app.get("/api/history")
    def api_history():
        limit = request.args.get("limit", 50, type=int)
        query = request.args.get("q", "").strip()
        if query:
            rows = ledger.search(query)
        else:
            rows = ledger.list_recent(limit)
        return jsonify({
            "panels": [
                {
                    "deidentified_id": r["deidentified_id"],
                    "external_id": r["external_id"],
                    "entered_by": r["entered_by"],
                    "entered_at": r["entered_at"],
                }
                for r in rows
            ],
            "count": ledger.count(),
            "ok": True,
        })

    @app.get("/api/history/<deidentified_id>")
    def api_history_one(deidentified_id: str):
        panel = ledger.get(deidentified_id)
        if panel is None:
            return jsonify({"error": "panel not found"}), 404
        envelope = ledger.get_envelope(deidentified_id)
        if envelope is None:
            envelope = {}
        return jsonify({
            "panel": panel,
            "analysis": envelope,
            "ok": True,
        })

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "engine": "abid", "db": str(db)})

    return app, ledger


def main() -> None:
    parser = argparse.ArgumentParser(description="Blood Banking Antibody ID console server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind (default 9120)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite ledger path")
    args = parser.parse_args()

    db = Path(args.db)
    app, ledger = build_app(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    print(f"Blood Banking Antibody ID console server on http://{args.host}:{args.port}")
    print(f"SQLite ledger: {db}  ({ledger.count()} panels)")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
