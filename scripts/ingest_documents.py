"""Extract and chunk trusted PDF / DOCX demo documents for BigQuery lexical RAG.

This is an OPERATOR-OFFLINE ingestion job, not a public upload endpoint.
The PDF parser is an optional development dependency (uv run --with pypdf).
DOCX text is extracted with the Python standard library only.

Usage:
  uv run --with pypdf python -m scripts.ingest_documents --execute
  uv run python -m scripts.seed_bigquery --project PROJECT --include-documents --execute
"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import re
import zipfile
import xml.etree.ElementTree as ET

from autoclaim_agent.documents import catalog
from autoclaim_agent.retrieval import normalize
from autoclaim_agent.repository import ROOT

OUTPUT = ROOT / "contracts" / "ingested_documents.jsonl"
MAX_PAGES = 30
MAX_TEXT_CHARS = 120_000
CHUNK_SIZE = 1100


def extract_pdf(path: Path) -> list[tuple[str, str]]:
    """Extract text pages with pypdf; image-only pages are NOT OCR'ed."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install pypdf for ingestion: uv run --with pypdf ...") from exc
    reader = PdfReader(str(path), strict=True)
    if len(reader.pages) > MAX_PAGES:
        raise ValueError("Too many PDF pages")
    result = []
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if text.strip():
            result.append((f"P{index:03d}", text[:MAX_TEXT_CHARS]))
    if not result:
        raise ValueError(f"PDF without extractable text (OCR not available): {path.name}")
    return result


def extract_docx(path: Path) -> list[tuple[str, str]]:
    """Read document text (including tables) without running macros or code."""
    # Cap decompressed XML to avoid handling oversized ZIP entries.
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > MAX_TEXT_CHARS * 8:
            raise ValueError("DOCX XML too large")
        root = ET.fromstring(archive.read(info))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for p in root.findall(".//w:p", ns):
        text = "".join(node.text or "" for node in p.findall(".//w:t", ns)).strip()
        if text:
            paragraphs.append(text)
    if not paragraphs:
        raise ValueError("Empty DOCX document")
    return [("S001", "\n".join(paragraphs)[:MAX_TEXT_CHARS])]


def split_text(text: str, *, width: int = CHUNK_SIZE) -> list[str]:
    """Chunk by word boundary; never silently drop the tail."""
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    chunks = []
    while clean:
        if len(clean) <= width:
            chunks.append(clean)
            break
        boundary = clean.rfind(" ", width // 2, width + 1)
        if boundary < 0:
            boundary = width
        chunks.append(clean[:boundary].strip())
        clean = clean[boundary:].strip()
    return chunks


def build_document_rows(entries: tuple[dict, ...] | None = None) -> list[dict]:
    """Produce BigQuery rows with citation, date and ACL on every chunk."""
    source_entries = entries if entries is not None else catalog()
    rows: list[dict] = []
    citations: set[str] = set()
    for item in source_entries:
        path = Path(item["path"])
        extractor = extract_pdf if path.suffix.lower() == ".pdf" else extract_docx
        chunks = extractor(path)
        for section, page_text in chunks:
            for index, chunk in enumerate(split_text(page_text), 1):
                chunk_section = f"{section}-{index:02d}"
                citation = f"{item['document_id']}@v{item['version']}#{chunk_section}"
                if citation in citations:
                    raise ValueError("Duplicate source citation")
                citations.add(citation)
                label = f"{item['title']} ({section})"
                rows.append({
                    "clause_id": f"{item['document_id']}#{chunk_section}",
                    "document_id": item["document_id"],
                    "version": item["version"],
                    "section": chunk_section,
                    "title": label,
                    "coverage_code": item["coverage_code"],
                    "clause_type": "document_excerpt",
                    "text": chunk,
                    "allowed_groups": item["allowed_groups"],
                    "effective_from": item["effective_from"],
                    "effective_to": item["effective_to"],
                    "citation": citation,
                    "search_text": normalize(label + " " + item["coverage_code"] + " " + chunk),
                })
    if not rows:
        raise ValueError("No document chunks extracted")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Build fictional PDF/DOCX BigQuery chunks")
    parser.add_argument("--execute", action="store_true", help="Write generated JSONL")
    args = parser.parse_args()
    rows = build_document_rows()
    print(f"Documents: {len(catalog())} | extracted chunks: {len(rows)}")
    print(f"Target: {OUTPUT}")
    if not args.execute:
        print("DRY RUN: add --execute to save the index")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print("OK: index generated. Run seed_bigquery with --include-documents.")


if __name__ == "__main__":
    main()
