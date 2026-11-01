"""Checks that PDFs and Word files are actually extracted and ACL-filtered."""

from pathlib import Path
import json

from autoclaim_agent.documents import catalog, get_document, list_documents
from autoclaim_agent.repository import find_claim
from autoclaim_agent.retrieval import LocalClauseRetriever
from autoclaim_agent.security import VerifiedPrincipal
from scripts.ingest_documents import extract_docx, extract_pdf, split_text
from scripts.seed_bigquery import build_rows

MANAGER = VerifiedPrincipal('manager', frozenset({'gestionnaires_auto'}))
SUPERVISOR = VerifiedPrincipal('supervisor', frozenset({'superviseurs_auto'}))
CLAIM = find_claim('SIN-1001')


def test_catalog_is_real_three_files():
    entries = catalog()
    assert len(entries) == 3
    assert {d['path'].suffix for d in entries} == {'.pdf', '.docx'}
    assert all(d['path'].is_file() for d in entries)


def test_pdf_text_extraction_interface_without_optional_parser(monkeypatch):
    """CI must pass without pypdf; actual sample PDFs are pre-extracted."""
    import sys
    from types import SimpleNamespace

    class FakePage:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class FakePdfReader:
        def __init__(self, path, strict=True):
            assert path.endswith('.pdf') and strict is True
            self.pages = [FakePage('Guide vitrage devis facture'), FakePage('Validation humaine')]

    monkeypatch.setitem(sys.modules, 'pypdf', SimpleNamespace(PdfReader=FakePdfReader))
    pages = extract_pdf(next(d['path'] for d in catalog() if d['path'].suffix == '.pdf'))
    assert pages == [('P001', 'Guide vitrage devis facture'), ('P002', 'Validation humaine')]


def test_docx_text_is_extracted_from_xml():
    entry = next(d for d in catalog() if d['document_id'] == 'DOC-PROCEDURE-AUTO-2026')
    chunks = extract_docx(entry['path'])
    assert 'franchise' in chunks[0][1].lower()
    assert 'documents' not in chunks[0][0].lower()


def test_chunks_cover_entire_text():
    text = 'mot ' * 1200
    result = split_text(text)
    assert len(result) > 2
    assert ' '.join(result) == text.strip()


def test_exact_index_rows_and_unique_citations():
    # Bundled real extracted chunks: no optional PDF parser required in CI.
    from autoclaim_agent.repository import ROOT
    source = ROOT / 'contracts' / 'ingested_documents.jsonl'
    rows = [json.loads(line) for line in source.read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(rows) >= 4
    assert all(r['clause_type'] == 'document_excerpt' for r in rows)
    assert all(r['search_text'] for r in rows)
    assert len({r['citation'] for r in rows}) == len(rows)
    assert any('#P001-01' in r['citation'] for r in rows)


def test_bq_seed_adds_real_document_chunks_opt_in_only():
    assert len(build_rows()) == 7
    complete = build_rows(include_documents=True)
    assert len(complete) >= 11
    assert any(r['document_id'].startswith('DOC-') for r in complete)


def test_manager_does_not_see_supervisor_document():
    visible = list_documents(CLAIM, MANAGER)
    assert len(visible) == 2
    assert all(d['document_id'] != 'DOC-CONTROLE-SENSIBLE-2026' for d in visible)
    assert get_document(CLAIM, MANAGER, 'DOC-CONTROLE-SENSIBLE-2026') is None


def test_supervisor_can_see_sensitive_document():
    visible = list_documents(CLAIM, SUPERVISOR)
    assert len(visible) == 3
    assert get_document(CLAIM, SUPERVISOR, 'DOC-CONTROLE-SENSIBLE-2026') is not None


def test_documents_not_returned_outside_period():
    old_claim = find_claim('SIN-1006')
    assert list_documents(old_claim, MANAGER) == []


def test_local_retriever_docs_are_acl_scoped():
    index = LocalClauseRetriever(include_documents=True)
    manager_matches = index.search(
        'supervision confidentielle', verified_groups=MANAGER.groups,
        event_date='2026-10-20', limit=10,
    )
    assert all(row['document_id'] != 'DOC-CONTROLE-SENSIBLE-2026' for row in manager_matches)
    supervisor_matches = index.search(
        'supervision confidentielle', verified_groups=SUPERVISOR.groups,
        event_date='2026-10-20', limit=10,
    )
    assert any(row['document_id'] == 'DOC-CONTROLE-SENSIBLE-2026' for row in supervisor_matches)


def test_local_retriever_contains_pdf_justificatifs():
    rows = LocalClauseRetriever(include_documents=True).search(
        'justificatifs facture photos vitrage', verified_groups=MANAGER.groups,
        event_date='2026-10-30', coverage_code='BRIS_GLACE', limit=10,
    )
    assert any(row['document_id'] == 'DOC-GUIDE-BG-2026' for row in rows)
