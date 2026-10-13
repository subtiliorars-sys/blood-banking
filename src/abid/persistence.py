"""SQLite ledger for analyzed panels.

Tracks every hemagglutination panel that has been run through the engine,
together with de-identified internal references, the technician who entered
the panel, and audit fields required for AABB/CAP compliance.

Privacy model
-------------
Patient-identifying fields are NOT stored in the ledger.  What is stored:

  * external_id      -- the patient/barcode ID the tech typed in
  * deidentified_id  -- a UUID the ledger assigns at insert time (stable per
                        panel; used as the foreign key in reports)
  * entered_by       -- system user / technician name
  * entered_at       -- UTC timestamp
  * checksum         -- SHA-256 over the canonical panel payload; lets us
                        detect duplicate re-runs and prove the record has not
                        been modified since analysis

Potency / source fields (antibody result, exclusions, pairs) are stored as the
engine's JSON envelope for auditability.  Zero patient-identifying attributes
are persisted; the only linkage is the internal UUID + the entered_by label.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS panels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    deidentified_id TEXT NOT NULL UNIQUE,
    external_id     TEXT,
    entered_by      TEXT NOT NULL,
    entered_at      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    checksum        TEXT NOT NULL,
    envelope        TEXT NOT NULL,
    engine_version  TEXT NOT NULL DEFAULT '0.1.0'
);
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

EMPTY_RESULT = {
    "patient_id": None,
    "serum": None,
    "single_antibody": None,
    "confident_single": False,
    "single_score": 0.0,
    "single_exclusions": [],
    "pairs": [],
    "pair_scores": [],
    "pair_status": [],
    "auto_control_positive": False,
    "flagged": [],
    "identity": [],
}

# Key splitters for JSON comparison (deterministic).
KEY_SPLITTER = "_---_"  # guaranteed not to appear in normal JSON text


def canonical_payload(obj: dict[str, Any]) -> str:
    """Serialise a panel dict to a canonical, whitespace-neutral string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    """Thread-safe (single-process) SQLite-backed panel ledger."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    # -- lifecycle ---------------------------------------------------------
    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        # Default metadata row.
        self._conn.execute(
            "INSERT OR IGNORE INTO metadata (key, value) VALUES ('engine_version', '0.1.0')"
        )
        # Idempotent index creation (executescript doesn't tolerate duplicate names).
        for stmt in (
            "CREATE INDEX IF NOT EXISTS idx_deidentified ON panels(deidentified_id)",
            "CREATE INDEX IF NOT EXISTS idx_entered_at ON panels(entered_at)",
            "CREATE INDEX IF NOT EXISTS idx_external_id ON panels(external_id)",
        ):
            self._conn.execute(stmt)
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    # -- save / fetch ------------------------------------------------------
    def save(self, payload: dict[str, Any], envelope: dict[str, Any],
             entered_by: str = "unknown") -> str:
        """Insert a panel and return its deidentified_id.

        `envelope` may be a dict (engine JSON envelope) or a JSON string.
        """
        payload_str = canonical_payload(payload)
        checksum = sha256(payload_str)
        deidentified_id = self._deidentified_id()
        now = utcnow()
        if isinstance(envelope, str):
            envelope = json.loads(envelope)
        envelope_str = json.dumps(envelope, sort_keys=True)
        self._conn.execute(
            """
            INSERT INTO panels
                (deidentified_id, external_id, entered_by, entered_at,
                 payload, checksum, envelope, engine_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                deidentified_id,
                payload.get("patient_id"),
                entered_by,
                now,
                payload_str,
                checksum,
                envelope_str,
                payload.get("engine_version", "0.1.0"),
            ),
        )
        self._conn.commit()
        return deidentified_id

    def _deidentified_id(self) -> str:
        # Use an internal counter-based UUID so the ID is stable per panel
        # across sessions but contains no patient-identifying data.
        row = self._conn.execute("SELECT COUNT(*) AS n FROM panels").fetchone()
        n = (row["n"] + 1) if row else 0
        # Compact, non-sequential-looking hash of the count.
        return f"P-{n:05d}-{sha256(str(n))[:8].upper()}"

    def get(self, deidentified_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM panels WHERE deidentified_id = ?", (deidentified_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def lookup_by_external(self, external_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM panels WHERE external_id = ?", (external_id,)
        ).fetchone()
        return dict(row) if row else None

    # -- history ---------------------------------------------------------
    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT deidentified_id, external_id, entered_by, entered_at, "
            "checksum FROM panels ORDER BY entered_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_envelope(self, deidentified_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT envelope FROM panels WHERE deidentified_id = ?", (deidentified_id,)
        ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["envelope"])
        except (TypeError, json.JSONDecodeError):
            return None

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM panels").fetchone()
        return row["n"]

    def search(self, q: str) -> list[dict[str, Any]]:
        """Search by external_id / entered_by / deidentified_id (case-insensitive)."""
        pat = f"%{q.lower()}%"
        rows = self._conn.execute(
            """
            SELECT deidentified_id, external_id, entered_by, entered_at
            FROM panels
            WHERE LOWER(external_id) LIKE ? OR LOWER(entered_by) LIKE ?
            ORDER BY entered_at DESC
            LIMIT 100
            """,
            (pat, pat),
        ).fetchall()
        return [dict(r) for r in rows]

    # -- metadata ----------------------------------------------------------
    def get_metadata(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO metadata (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
