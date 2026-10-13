"""AABB/CAP documentation export.

Produces the audit and documentation artifacts a blood bank needs for routine
regulatory reporting.  The module is format-agnostic at the boundary and
currently emits JSON (structured, machine-read and human-viewable) plus CSV
(picklist-friendly).  A PDF/HTML view can be added behind a flag once the
schema is fixed.

Document set
------------
1. investigational_report   - the antibody ID interpretation, single + pairs
                              + decomposition suggestions (the clinical
                              decision support output)
2. quality_forms            - completed / missed quality-check items we track
                              (auto-control, DAT, auto-control positive flag)
3. patient_ledger           - the deidentified patient ledger: who ran what,
                              when, on which external ID, and the checksum
                              proving the record is immutable
4. transfusion_component    - the transfusion component record: component,
                              volume, patient component RCC number, effect and
                              outcome, and the post-transfusion anti-body
                              studies (per AABB 5.40)
5. laboratory_workspace     - the full workspace snapshot: engine version,
                              panel checksums, deidentified_id + envelope,
                              and the external ID -> deidentified ID mapping
                              (the audit chain from entry to interpretation)

All documents share a header carrying:
  - site / program label
  - generated_at (UTC)
  - engine_version
  - the deidentified_id (internal reference, never the patient external ID)

Privacy
-------
- No patient-identifying fields are included in the export.
- The only linkage is the internal deidentified_id + the entered_by label.
- If the caller passes an external_id filter, the export carries that ID as an
  opaque reference (the same value the tech typed in) but never a name or DOB.
"""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Optional

from .persistence import Ledger, canonical_payload, sha256


# ---------------------------------------------------------------------------
# Shared document header
# ---------------------------------------------------------------------------
def document_header(site_label: str, engine_version: str, generated_at: Optional[str] = None) -> dict[str, Any]:
    return {
        "site_label": site_label or "unknown-site",
        "generated_at": generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine_version": engine_version or "0.1.0",
        "export_id": _export_id(),
    }


def _export_id() -> str:
    """Stable, deidentified export handle (epoch nanoseconds, no PII)."""
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------
def build_investigational_report(
    external_id: str,
    deidentified_id: str,
    entered_by: str,
    entered_at: str,
    panel: dict[str, Any], envelope: dict[str, Any], decomp: list[dict[str, Any]]
) -> dict[str, Any]:
    ident = envelope.get("identity", []) or []
    if isinstance(ident, list):
        identity_rows = ident
    else:
        identity_rows = []

    # Map the single result.
    single = envelope.get("single_antibody")
    single_score = envelope.get("single_score", 0.0)
    confident = bool(envelope.get("confident_single", False))
    exclusions = envelope.get("single_exclusions", []) or []

    # Pair result.
    pairs = envelope.get("pairs", []) or []
    pair_scores = envelope.get("pair_scores", []) or []
    pair_status = envelope.get("pair_status", []) or []

    # Decomposition.
    decomp_suggestions = []
    for d in (decomp or []):
        decomp_suggestions.append(
            {
                "type": d.get("suggestion_type", "unknown"),
                "title": d.get("title", ""),
                "priority": d.get("priority", 0),
                "cells": d.get("cells", []),
                "why": d.get("why", ""),
                "action": d.get("action", ""),
                "expected": d.get("expected", ""),
            }
        )

    return {
        "document_type": "investigational_report",
        "patient_external_id": external_id,
        "deidentified_id": deidentified_id,
        "entered_by": entered_by,
        "entry_datetime": entered_at,
        "engine_version": panel.get("engine_version", "0.1.0"),
        "panel": {
            "cells": [
                {"cell_id": r["cell_id"], "phenotype": r.get("phenotype"), "grade": r.get("grade")}
                for r in identity_rows
            ],
        },
        "single_antibody_interpretation": {
            "antibody": single,
            "confidence": single_score,
            "confident": confident,
            "exclusions": exclusions,
        },
        "two_antibody_interpretation": {
            "pairs": [
                {"pair": p, "score": pair_scores[i], "status": pair_status[i] if i < len(pair_status) else "review"}
                for i, p in enumerate(pairs)
            ]
            if pairs
            else [],
        },
        "decomposition_suggestions": decomp_suggestions,
    }


def build_quality_forms(
    external_id: str,
    deidentified_id: str,
    entered_by: str,
    entered_at: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    ident = envelope.get("identity", []) or []
    auto_positive = bool(
        envelope.get("auto_control_positive")
        or any(row.get("autocontrol") for row in ident if isinstance(row, dict))
    )
    return {
        "document_type": "quality_forms",
        "patient_external_id": external_id,
        "deidentified_id": deidentified_id,
        "entered_by": entered_by,
        "entry_datetime": entered_at,
        "auto_control_positive": auto_positive,
        "auto_control_cells": [
            r["cell_id"] for r in ident if isinstance(r, dict) and r.get("autocontrol")
        ],
        "post_transfusion_anti_calculations": "Not performed in this run",
        "quality_check_list": [
            {
                "item": "auto_control_positive",
                "value": auto_positive,
                "defined_as": "Auto-control >= 1+",
            },
            {
                "item": "auto_control_cells",
                "value": len([r for r in ident if isinstance(r, dict) and r.get("autocontrol")]),
                "defined_as": "Number of auto-control cells",
            },
            {
                "item": "reactive_cells",
                "value": len([r for r in ident if isinstance(r, dict) and r.get("status") == "positive"]),
                "defined_as": "Reactive cells",
            },
            {
                "item": "negative_cells",
                "value": len([r for r in ident if isinstance(r, dict) and r.get("status") == "negative"]),
                "defined_as": "Negative cells",
            },
        ],
    }


def build_patient_ledger(
    panels: list[dict[str, Any]],
    site_label: str,
    engine_version: str,
) -> dict[str, Any]:
    """One row per panel, deidentified, with payload checksum for immutability."""
    rows = []
    for p in panels:
        rows.append(
            {
                "deidentified_id": p.get("deidentified_id"),
                "external_id": p.get("external_id"),
                "entered_by": p.get("entered_by"),
                "entered_at": p.get("entered_at"),
                "checksum": p.get("checksum"),
                "payload_sha256": p.get("payload"),
            }
        )
    return {
        "document_type": "patient_ledger",
        "site_label": site_label,
        "engine_version": engine_version,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": rows,
    }


def build_transfusion_component(
    component_id: str,
    patient_external_id: str,
    deidentified_id: str,
    entered_by: str,
    effect: Optional[str] = None,
    outcome: Optional[str] = None,
    post_transfusion_antibody_study: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "document_type": "transfusion_component",
        "site_label": "unknown-site",
        "component_id": component_id,
        "patient_external_id": patient_external_id,
        "deidentified_id": deidentified_id,
        "entered_by": entered_by,
        "entry_datetime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "component": {
            "component_id": component_id,
            "volume": None,  # supplied from the component record
            "patient_component_rcc_number": None,
            "effect": effect,
            "outcome": outcome,
        },
        "post_transfusion_antibody_study": post_transfusion_antibody_study or "Not performed in this run",
    }


def build_workspace_snapshot(
    site_label: str,
    engine_version: str,
    db_path: str,
    source: str = "panel upload",
) -> dict[str, Any]:
    return {
        "document_type": "laboratory_workspace",
        "site_label": site_label,
        "engine_version": engine_version,
        "source": source,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ledger_path": db_path,
        "panel_checksums": [
            {
                "deidentified_id": p.get("deidentified_id"),
                "external_id": p.get("external_id"),
                "checksum": p.get("checksum"),
            }
            for p in (Ledger(db_path).list_recent() if os.path.exists(db_path) else [])
        ],
    }


# ---------------------------------------------------------------------------
# Serialisation: JSON (pretty) + CSV
# ---------------------------------------------------------------------------
def export_json(documents: dict[str, Any], path: Path, header: dict[str, Any]) -> Path:
    """Write a JSON document bundle with a top-level header."""
    payload = {"header": header, "documents": documents}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def export_csv(documents: dict[str, Any], path: Path) -> Path:
    """Write a CSV per document type.  Each CSV is a picklist-friendly flat view.

    The operational picklist is the patient ledger: deidentified_id, external
    ID, entered_by, entered_at.  Reports and quality forms are written as
    CSV rows where the source document has a flat row representation.
    """
    # Flat CSV of the patient ledger rows.
    ledger_rows = documents.get("patient_ledger", {}).get("rows", [])
    if ledger_rows:
        fieldnames = ["deidentified_id", "external_id", "entered_by", "entered_at", "checksum"]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in ledger_rows:
                writer.writerow(r)

    # Flat CSV of the investigational report.
    report = documents.get("investigational_report", {})
    if report:
        fieldnames = [
            "deidentified_id", "antibody", "confidence", "pair", "score", "status"
        ]
        with path.with_name(path.stem + "_report.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for p in report.get("two_antibody_interpretation", {}).get("pairs", []):
                writer.writerow(
                    {
                        "deidentified_id": report.get("deidentified_id"),
                        "antibody": report.get("single_antibody_interpretation", {}).get("antibody"),
                        "confidence": report.get("single_antibody_interpretation", {}).get("confidence"),
                        "pair": ",".join(p.get("pair", [])),
                        "score": p.get("score"),
                        "status": p.get("status"),
                    }
                )

    # Flat CSV of quality forms.
    quality = documents.get("quality_forms", {})
    if quality:
        fieldnames = [
            "deidentified_id", "auto_control_positive", "auto_control_cells",
            "reactive_cells", "negative_cells",
        ]
        with path.with_name(path.stem + "_quality.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerow(
                {
                    "deidentified_id": quality.get("deidentified_id"),
                    "auto_control_positive": quality.get("auto_control_positive"),
                    "auto_control_cells": len(quality.get("auto_control_cells", [])),
                    "reactive_cells": _quality_value(quality.get("quality_check_list", []), "reactive_cells"),
                    "negative_cells": _quality_value(quality.get("quality_check_list", []), "negative_cells"),
                }
            )

    return path


# ---------------------------------------------------------------------------
# Top-level export builder
# ---------------------------------------------------------------------------
def _quality_value(checklist: list[dict[str, Any]], item: str) -> Any:
    for entry in checklist:
        if isinstance(entry, dict) and entry.get("item") == item:
            return entry.get("value")
    return 0


def build_export(
    site_label: str,
    engine_version: str,
    ledger_path: str,
    deidentified_id: str,
    external_id: str,
    entered_by: str,
    entered_at: str,
    panel: dict[str, Any],
    envelope: dict[str, Any],
    decomp: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Assemble all documents for one analyzed panel."""
    if not deidentified_id:
        raise ValueError("deidentified_id is required")

    header = document_header(site_label, engine_version)

    # One-row patient ledger for this panel.
    payload = canonical_payload(panel)
    checksum = sha256(payload)
    ledger_row = {
        "deidentified_id": deidentified_id,
        "external_id": external_id,
        "entered_by": entered_by,
        "entered_at": entered_at,
        "checksum": checksum,
        "payload_sha256": payload,
    }

    return {
        "investigational_report": build_investigational_report(
            external_id, deidentified_id, entered_by, entered_at,
            panel, envelope, decomp or []
        ),
        "quality_forms": build_quality_forms(
            external_id, deidentified_id, entered_by, entered_at, envelope
        ),
        "patient_ledger": {
            "site_label": site_label,
            "engine_version": engine_version,
            "generated_at": header["generated_at"],
            "rows": [ledger_row],
        },
        "transfusion_component": build_transfusion_component(
            component_id="COMP-" + (external_id or "XXXXXXXX"),
            patient_external_id=external_id or "unknown",
            deidentified_id=deidentified_id,
            entered_by=entered_by or "unknown",
            effect=None,
            outcome=None,
            post_transfusion_antibody_study="Not performed in this run",
        ),
        "laboratory_workspace": build_workspace_snapshot(
            site_label, engine_version, ledger_path, source="panel upload"
        ),
    }
