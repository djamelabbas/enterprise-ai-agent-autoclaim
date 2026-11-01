"""Release V3: approved OCR lineage, RAG gold set and IAP document ACL.

All checks are offline. The real GCP benchmark is a separate release gate.
OCR approval artifacts are committed in the demo repository intentionally:
they are fictional and were human-reviewed before indexing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoclaim_agent.documents import catalog, accessible_claim, get_document
from autoclaim_agent.repository import find_claim
from autoclaim_agent.security import VerifiedPrincipal
from autoclaim_api.app import build_app
from autoclaim_api.iap_auth import AuthenticatedUser, InvalidIdentity
from autoclaim_api.roles import resolve_groups
from scripts.evaluate_retrieval import metrics, ROOT as EVAL_ROOT
from scripts.ingest_images import INDEX, MANIFEST, candidates
from scripts.seed_bigquery import build_rows

OCR = "DOC-CONSTAT-VISUEL-2026@v1.0#IMG-01"
DOC_ID = "DOC-CONSTAT-VISUEL-2026"
# Fixed digest for the fictional PNG shipped with the project.
APPROVED_SHA256 = "a8635976b2cf226226d954b36634d7778ca95de0e824873e0a67648d72d60c16"


def _golden():
    return json.loads((EVAL_ROOT / "data/retrieval_golden.json").read_text(encoding="utf-8"))


def test_golden_has_positive_ocr_query_and_two_access_negative_cases():
    gold = _golden()
    assert len(gold) == 15
    assert len({item["id"] for item in gold}) == len(gold)
    positive = next(item for item in gold if item["id"] == "Q13")
    assert positive["expected"] == [OCR]
    assert positive["coverage_code"] == "BRIS_GLACE"
    assert positive["event_date"] == "2026-10-30"
    negatives = {item["id"]: item for item in gold if item["id"] in ("Q14", "Q15")}
    assert set(negatives) == {"Q14", "Q15"}
    assert all(OCR in row["forbidden"] and not row["expected"] for row in negatives.values())
    assert negatives["Q14"]["event_date"] == "2027-02-01"
    assert negatives["Q15"]["coverage_code"] == "VOL"


def test_approved_ocr_artifacts_and_source_fingerprint_are_versioned():
    assert INDEX.is_file(), "Approve OCR locally and include contracts/ingested_images.jsonl in Git"
    assert MANIFEST.is_file(), "Include the reviewed demo_documents/manifest_images.json in Git"
    inputs = candidates()
    assert len(inputs) == 1
    assert inputs[0]["sha256"] == APPROVED_SHA256
    rows = [json.loads(s) for s in INDEX.read_text(encoding="utf-8").splitlines() if s.strip()]
    assert len(rows) == 1
    assert rows[0]["citation"] == OCR
    assert rows[0]["document_id"] == DOC_ID
    assert rows[0]["coverage_code"] == "BRIS_GLACE"
    assert rows[0]["allowed_groups"] == ["gestionnaires_auto", "superviseurs_auto"]
    assert rows[0]["effective_from"] <= "2026-10-30" <= rows[0]["effective_to"]
    content = rows[0]["text"].lower()
    assert "600 eur" in content and "non signe" in content
    assert "verification humaine" in content and "non certifie" in content


def test_ocr_manifest_corresponds_to_indexed_document():
    index = json.loads(INDEX.read_text(encoding="utf-8").splitlines()[0])
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]
    assert len(manifest) == 1
    row = manifest[0]
    assert row["document_id"] == index["document_id"]
    assert row["version"] == index["version"]
    assert row["allowed_groups"] == index["allowed_groups"]
    assert row["coverage_code"] == index["coverage_code"]
    assert row["filename"] == "constat_visuel_demo.png"
    assert (INDEX.parent.parent / "demo_documents" / row["filename"]).is_file()


def test_approved_corpus_has_twelve_unique_chunks_with_ocr_opt_in():
    assert len(build_rows(include_documents=True)) == 11
    rows = build_rows(include_documents=True, include_images=True)
    assert len(rows) == 12
    assert len({row["citation"] for row in rows}) == 12
    assert sum(row["citation"] == OCR for row in rows) == 1


def test_image_visible_only_on_authorized_claim_and_validity():
    manager = VerifiedPrincipal("manager", frozenset({"gestionnaires_auto"}))
    yes = accessible_claim("SIN-1001", manager)
    assert yes is not None
    assert get_document(yes, manager, DOC_ID) is not None
    assert accessible_claim("SIN-1004", manager) is None
    for claim_id in ("SIN-1002", "SIN-1006"):
        claim = accessible_claim(claim_id, manager)
        assert claim is not None
        assert get_document(claim, manager, DOC_ID) is None


@pytest.fixture
def browser(monkeypatch):
    aud = "/projects/123/locations/europe-west1/services/autoclaim-mvp"
    monkeypatch.setenv("AUTOCLAIM_IAP_AUDIENCE", aud)
    monkeypatch.setenv("AUTOCLAIM_MANAGER_EMAILS", "manager@example.com")
    monkeypatch.setenv("AUTOCLAIM_SUPERVISOR_EMAILS", "supervisor@example.com")

    def verify(token, audience):
        assert audience == aud
        if token == "manager":
            return AuthenticatedUser("manager", "manager@example.com")
        if token == "supervisor":
            return AuthenticatedUser("supervisor", "supervisor@example.com")
        raise InvalidIdentity("not authenticated")

    from autoclaim_agent.retrieval import LocalClauseRetriever
    return TestClient(build_app(
        verifier=verify,
        role_resolver=resolve_groups,
        retriever_factory=lambda: LocalClauseRetriever(include_documents=True),
    ))


def test_approved_png_served_with_mime_and_private_cache(browser):
    path = f"/api/claims/SIN-1001/documents/{DOC_ID}"
    response = browser.get(path, headers={"X-Goog-IAP-JWT-Assertion": "manager"})
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["cache-control"] == "private, no-store"
    assert "inline" in response.headers.get("content-disposition", "")
    assert browser.get(path).status_code == 401


def test_image_endpoint_does_not_bypass_claim_or_document_acl(browser):
    prefix = "/api/claims/"
    for claim_id in ("SIN-1002", "SIN-1006", "SIN-1004", "SIN-9999"):
        resp = browser.get(f"{prefix}{claim_id}/documents/{DOC_ID}", headers={"X-Goog-IAP-JWT-Assertion": "manager"})
        assert resp.status_code == 404
        assert "PNG" not in resp.text
    # Existing confidential Word still cannot be downloaded by manager.
    resp = browser.get(f"{prefix}SIN-1001/documents/DOC-CONTROLE-SENSIBLE-2026", headers={"X-Goog-IAP-JWT-Assertion": "manager"})
    assert resp.status_code == 404


def test_golden_ocr_metrics_detect_a_missing_or_forbidden_image():
    # This verifies the evaluation gate itself without network/GCP.
    positive, expired, wrong_coverage = (next(q for q in _golden() if q["id"] == qid) for qid in ("Q13", "Q14", "Q15"))
    good = metrics([positive, expired, wrong_coverage], [[OCR], [], []])
    assert good["hit_at_5"] == 1.0
    assert good["forbidden_citation_count"] == 0
    missing = metrics([positive, expired, wrong_coverage], [[], [], []])
    assert missing["hit_at_5"] == 0.0
    leaked = metrics([positive, expired, wrong_coverage], [[OCR], [OCR], [OCR]])
    assert leaked["forbidden_citation_count"] == 2
