"""P3: mandatory human approval, digest check, bounded OCR schema."""
from pathlib import Path
import pytest
from scripts.ingest_images import candidates, approve


def test_demo_png_is_approved_input_format():
    rows = candidates()
    assert len(rows) == 1
    assert rows[0]["mime"] == "image/png"
    assert rows[0]["sha256"] and rows[0]["path"].is_file()


def test_approval_generates_versioned_citation_without_api():
    rows = candidates()
    pending = [{"sha256": rows[0]["sha256"], "extraction": {
        "transcription": "Observation vitrage fissure", "description": "Fissure simulee",
        "difficultes_lecture": "aucune",
    }}]
    index, manifest = approve(rows, pending)
    assert index[0]["citation"] == "DOC-CONSTAT-VISUEL-2026@v1.0#IMG-01"
    assert "OCR" in index[0]["text"]
    assert index[0]["allowed_groups"] == ["gestionnaires_auto", "superviseurs_auto"]
    assert manifest[0]["filename"] == "constat_visuel_demo.png"


def test_changed_image_is_not_approved():
    rows = candidates()
    with pytest.raises(ValueError): approve(rows, [{"sha256":"0"*64,"extraction":{"transcription":"faux"}}])


def test_image_catalog_follows_operator_approval():
    from autoclaim_agent.documents import catalog
    from scripts.ingest_images import MANIFEST
    visible = "DOC-CONSTAT-VISUEL-2026" in {x["document_id"] for x in catalog()}
    assert visible is MANIFEST.exists()


def test_image_index_is_opt_in():
    from scripts.seed_bigquery import build_rows
    from scripts.ingest_images import INDEX
    assert len(build_rows(include_documents=True)) == 11
    if INDEX.exists():
        assert len(build_rows(include_documents=True, include_images=True)) == 12
    else:
        with pytest.raises(FileNotFoundError): build_rows(include_documents=True, include_images=True)
