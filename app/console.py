#!/usr/bin/env python3
"""Console launcher for the Blood Banking Antibody ID frontend.

Serving the static UI (index.html, styles.css, main.js) and exposing a small
HTTP API that runs the `abid` engine.

Endpoints:
  GET  /              -> index.html
  GET  /api/analyze   -> JSON envelope from the engine
  POST /analyze       -> same, but the input JSON is in the request body
                        (Content-Type: application/json, {payload: str})

Run:
    python console.py            # serve on 0.0.0.0:9120
    python console.py --host 127.0.0.1 --port 9119
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent.parent  # app/
UI_DIR = BASE_DIR / "app" / "build" / "win" / "dist"
SYS_PYTHON = sys.executable
DEFAULT_PORT = 9120


def engine_stdout(input_json: str, patient_id: str, serum: str) -> str:
    """Run the engine and return its JSON envelope on stdout.

    The engine is invoked as a subprocess with the panel JSON piped to its
    stdin (as the positional `input`).  It reads that JSON, identifies the
    antibodies, and prints a JSON envelope to stdout.
    """
    cmd = [
        SYS_PYTHON, "-m", "abid.scripts.cli",
        "--json",
        "-p", patient_id,
        "-",  # read JSON panel from stdin (positional)
    ]
    proc = subprocess.run(
        cmd,
        input=input_json.encode("utf-8"),
        cwd=str(BASE_DIR.parent),  # root: /opt/data/blood-banking
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"engine failed ({proc.returncode}): {err}")
    return proc.stdout.decode("utf-8")


def build_app(ui_dir: Path) -> Flask:
    app = Flask(
        __name__,
        static_folder=str(ui_dir / "styles"),
        static_url_path="/styles",
    )

    @app.get("/")
    def index():
        return send_from_directory(ui_dir, "index.html")

    @app.get("/<path:path>")
    def static_file(path: str):
        # Serve everything else (js, css, images, samples) from the UI dir.
        return send_from_directory(ui_dir, path)

    @app.post("/analyze")
    def analyze():
        data = request.get_json(silent=True) or {}
        payload = data.get("payload", "")
        patient_id = data.get("patient_id", "unknown")
        serum = data.get("serum", "serum")
        try:
            stdout = engine_stdout(payload, patient_id, serum)
            return jsonify(json.loads(stdout))
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": str(exc)}), 500

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok", "engine": "abid"})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Blood Banking Antibody ID console server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind (default 9120)")
    parser.add_argument("--ui-dir", default=str(str(UI_DIR)), help="Directory containing the UI files")
    args = parser.parse_args()

    ui_dir = Path(args.ui_dir)

    app = build_app(ui_dir)
    print(f"Blood Banking Antibody ID console server on http://{args.host}:{args.port}")
    print(f"Serving UI from {ui_dir}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
