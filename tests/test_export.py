"""Unit tests for the AABB/CAP documentation export module."""

import csv
import json
import os
import tempfile
from pathlib import Path

import pytest

from abid.persistence import Ledger, canonical_payload
from abid import export as abe


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_panel():
    return {
        "patient_id": "PT-12345",
        "serum": "serum-A",
        "cells": {
            "C1": ["K"],
            "C2": ["K"],
            "C3": ["K"],
            "C4": ["K"],
            "C5": ["K"],
        },
        "reactions": {
            "C1": {"grade": 3},
            "C2": {"grade": 3},
            "C3": {"grade": 3},
            "C4": {"grade": 3},
            "C5": {"grade": 3},
        },
    }


@pytest.fixture
def sample_envelope():
    return {
        "patient_id": "PT-12345",
        "serum": "serum-A",
        "single_antibody": "anti-K",
        "confident_single": True,
        "single_score": 1.0,
        "single_exclusions": [],
        "pairs": [["anti-E", "anti-K"]],
        "pair_scores": [0.85],
        "pair_status": ["confident"],
        "auto_control_positive": False,
        "flagged": [],
        "identity": [
            {"cell_id": "C1", "phenotype": "K", "grade": 3, "status": "positive"},
            {"cell_id": "C2", "phenotype": "K", "grade": 3, "status": "positive"},
            {"cell_id": "C3", "phenotype": "K", "grade": 3, "status": "positive"},
            {"cell_id": "C4", "phenotype": "K", "grade": 3, "status": "positive"},
            {"cell_id": "C5", "phenotype": "K", "grade": 3, "status": "positive"},
        ],
    }


@pytest.fixture
def sample_decomp():
    return [
        {
            "suggestion_type": "prozone",
            "title": "Prozone reaction suspected",
            "priority": 2,
            "cells": ["C1", "C2"],
            "why": "Strong reactions at grade 4+",
            "action": "Serial saline dilution",
            "expected": "Reactions re-appear at 2-3+",
        }
    ]


@pytest.fixture
def ledger_path(tmp_path):
    return os.path.join(tmp_path, "test.db")


# ---------------------------------------------------------------------------
# document_header
# ---------------------------------------------------------------------------
def test_document_header_has_required_fields():
    header = abe.document_header("Test Lab", "0.1.0")
    assert header["site_label"] == "Test Lab"
    assert header["engine_version"] == "0.1.0"
    assert header["generated_at"]
    assert header["export_id"]


# ---------------------------------------------------------------------------
# build_export
# ---------------------------------------------------------------------------
def test_build_export_assembles_all_documents(sample_panel, sample_envelope, sample_decomp, ledger_path):
    payload = canonical_payload(sample_panel)
    checksum = abe.sha256(payload)
    deidentified_id = "P-00001-" + "ABCDEF"

    docs = abe.build_export(
        "Test Lab",
        "0.1.0",
        ledger_path,
        deidentified_id,
        "PT-12345",
        "tech1",
        "2026-10-13T15:00:00Z",
        sample_panel,
        sample_envelope,
        sample_decomp,
    )

    assert "investigational_report" in docs
    assert "quality_forms" in docs
    assert "patient_ledger" in docs
    assert "transfusion_component" in docs
    assert "laboratory_workspace" in docs

    # Investigational report populated from the envelope + decomp.
    report = docs["investigational_report"]
    assert report["patient_external_id"] == "PT-12345"
    assert report["deidentified_id"] == deidentified_id
    assert report["entered_by"] == "tech1"
    assert report["single_antibody_interpretation"]["antibody"] == "anti-K"
    assert report["two_antibody_interpretation"]["pairs"] == [
        {"pair": ["anti-E", "anti-K"], "score": 0.85, "status": "confident"}
    ]
    assert len(report["decomposition_suggestions"]) == 1
    assert report["decomposition_suggestions"][0]["type"] == "prozone"


def test_build_export_quality_forms(sample_panel, sample_envelope, ledger_path):
    deidentified_id = "P-00001-" + "01234567"
    docs = abe.build_export(
        "Test Lab", "0.1.0", ledger_path, deidentified_id, "PT-12345",
        "tech1", "2026-10-13T15:00:00Z", sample_panel, sample_envelope, [],
    )
    quality = docs["quality_forms"]
    assert quality["auto_control_positive"] is False
    assert quality["quality_check_list"] is not None


def test_build_export_patient_ledger(sample_panel, sample_envelope, ledger_path):
    deidentified_id = "P-00001-" + "DEADBEEF"
    payload = canonical_payload(sample_panel)
    checksum = abe.sha256(payload)
    docs = abe.build_export(
        "Test Lab", "0.1.0", ledger_path, deidentified_id, "PT-12345",
        "tech1", "2026-10-13T15:00:00Z", sample_panel, sample_envelope, [],
    )
    row = docs["patient_ledger"]["rows"][0]
    assert row["deidentified_id"] == deidentified_id
    assert row["external_id"] == "PT-12345"
    assert row["entered_by"] == "tech1"
    assert row["checksum"] == checksum
    assert row["payload_sha256"] == payload


def test_build_export_transfusion_component(sample_panel, sample_envelope, ledger_path):
    deidentified_id = "P-00001-" + "CAFEBABE"
    docs = abe.build_export(
        "Test Lab", "0.1.0", ledger_path, deidentified_id, "PT-12345",
        "tech1", "2026-10-13T15:00:00Z", sample_panel, sample_envelope, [],
    )
    trans = docs["transfusion_component"]
    assert trans["document_type"] == "transfusion_component"
    assert trans["patient_external_id"] == "PT-12345"
    assert trans["deidentified_id"] == deidentified_id
    assert "COMP-" in trans["component_id"]


def test_build_export_workspace_snapshot(sample_panel, sample_envelope, ledger_path):
    deidentified_id = "P-00001-" + "FFFFFF00"
    docs = abe.build_export(
        "Test Lab", "0.1.0", ledger_path, deidentified_id, "PT-12345",
        "tech1", "2026-10-13T15:00:00Z", sample_panel, sample_envelope, [],
    )
    workspace = docs["laboratory_workspace"]
    assert workspace["document_type"] == "laboratory_workspace"
    assert workspace["engine_version"] == "0.1.0"
    assert workspace["source"] == "panel upload"


# ---------------------------------------------------------------------------
# export_json
# ---------------------------------------------------------------------------
def test_export_json_writes_bundle(ledger_path):
    docs = {
        "investigational_report": {
            "document_type": "investigational_report",
            "deidentified_id": "P-00001-" + "11111111",
        }
    }
    header = abe.document_header("Test Lab", "0.1.0")

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "export.json"
        result = abe.export_json(docs, out, header)
        assert result == out
        assert os.path.exists(out)
        parsed = json.loads(result.read_text(encoding="utf-8"))
        assert parsed["header"]["site_label"] == "Test Lab"
        assert parsed["documents"]["investigational_report"]["deidentified_id"] == "P-00001-" + "11111111"


# ---------------------------------------------------------------------------
# export_csv
# ---------------------------------------------------------------------------
def test_export_csv_writes_ledger_and_report(ledger_path):
    docs = {
        "patient_ledger": {
            "rows": [
                {
                    "deidentified_id": "P-00001-" + "AAAAAAAA",
                    "external_id": "PT-1",
                    "entered_by": "tech1",
                    "entered_at": "2026-10-13T15:00:00Z",
                    "checksum": "abc123",
                },
                {
                    "deidentified_id": "P-00002-" + "BBBBBBBB",
                    "external_id": "PT-2",
                    "entered_by": "tech2",
                    "entered_at": "2026-10-13T15:05:00Z",
                    "checksum": "def456",
                },
            ]
        },
        "investigational_report": {
            "document_type": "investigational_report",
            "deidentified_id": "P-00001-" + "AAAAAAAA",
            "single_antibody_interpretation": {"antibody": "anti-K", "confidence": 1.0},
            "two_antibody_interpretation": {
                "pairs": [
                    {"pair": ["anti-E", "anti-K"], "score": 0.85, "status": "confident"}
                ]
            },
        },
        "quality_forms": {
            "document_type": "quality_forms",
            "deidentified_id": "P-00001-" + "AAAAAAAA",
            "auto_control_positive": False,
            "auto_control_cells": [],
            "quality_check_list": [
                {"item": "reactive_cells", "value": 5},
                {"item": "negative_cells", "value": 0},
            ],
        },
    }

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "export"
        abe.export_csv(docs, out)

        ledger_path_out = out  # ledger CSV written to path (out itself)
        report_path_out = out.with_name(out.name + "_report.csv")
        quality_path_out = out.with_name(out.name + "_quality.csv")

        assert os.path.exists(ledger_path_out)
        rows = list(csv.DictReader(open(ledger_path_out, newline="", encoding="utf-8")))
        assert len(rows) == 2
        assert rows[0]["external_id"] == "PT-1"
        assert rows[1]["external_id"] == "PT-2"

        assert os.path.exists(report_path_out)
        report_rows = list(csv.DictReader(open(report_path_out, newline="", encoding="utf-8")))
        assert len(report_rows) == 1
        assert report_rows[0]["antibody"] == "anti-K"

        assert os.path.exists(quality_path_out)
        quality_rows = list(csv.DictReader(open(quality_path_out, newline="", encoding="utf-8")))
        assert len(quality_rows) == 1
        assert quality_rows[0]["auto_control_positive"] == "False"


# ---------------------------------------------------------------------------
# Privacy: no patient-identifying fields in export
# ---------------------------------------------------------------------------
def test_export_contains_no_patient_identifiers(sample_panel, sample_envelope, ledger_path):
    deidentified_id = "P-00001-" + "88888888"
    docs = abe.build_export(
        "Test Lab", "0.1.0", ledger_path, deidentified_id, "PT-12345",
        "tech1", "2026-10-13T15:00:00Z", sample_panel, sample_envelope, [],
    )

    payload = json.dumps(docs, sort_keys=True)
    assert "name" not in payload
    assert "dob" not in payload
    assert "address" not in payload
    assert "social" not in payload
    # Only the opaque external ID and internal deidentified_id should be present.
    assert "PT-12345" in payload  # opaque reference only
    assert "John" not in payload
