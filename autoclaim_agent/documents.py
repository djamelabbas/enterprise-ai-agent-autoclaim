"""Catalog of approved fictional documents, independent from the LLM.

Only an operator-controlled manifest is read. Access is decided using the
IAP-verified server principal and the real claim record. No user-provided
file paths, document roles or claim groups are trusted.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import re

from .repository import ROOT, find_claim
from .security import VerifiedPrincipal

DOC_ROOT = ROOT / "demo_documents"
DOCUMENT_ID_RE = re.compile(r"^DOC-[A-Z0-9-]{5,70}$")
ALLOWED_SUFFIXES = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    """Load a strictly bounded allowlist of bundled demo files."""
    path = DOC_ROOT / "manifest.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    entries = metadata.get("documents", [])
    # Image documents are OPTIONAL and only activated after operator approval.
    # This avoids exposing an unreviewed OCR asset through the document API.
    image_manifest = DOC_ROOT / "manifest_images.json"
    if image_manifest.is_file():
        extras = json.loads(image_manifest.read_text(encoding="utf-8"))
        entries = entries + extras.get("documents", [])
    if not isinstance(entries, list) or len(entries) > 50:
        raise ValueError("Document catalog invalid")
    seen: set[str] = set()
    accepted: list[dict] = []
    for item in entries:
        document_id = item["document_id"]
        if not DOCUMENT_ID_RE.fullmatch(document_id) or document_id in seen:
            raise ValueError("Invalid or duplicate document ID")
        filename = item["filename"]
        if Path(filename).name != filename or Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise ValueError("Invalid document filename")
        resolved = (DOC_ROOT / filename).resolve()
        if resolved.parent != DOC_ROOT.resolve() or not resolved.is_file():
            raise ValueError("Missing or escaping document file")
        if resolved.stat().st_size > 8_000_000:
            raise ValueError("Document exceeds size limit")
        if not set(item["allowed_groups"]) <= {"gestionnaires_auto", "superviseurs_auto"}:
            raise ValueError("Unrecognized role in document catalog")
        date.fromisoformat(item["effective_from"])
        date.fromisoformat(item["effective_to"])
        accepted.append({**item, "path": resolved})
        seen.add(document_id)
    return tuple(accepted)


def accessible_claim(claim_id: str, principal: VerifiedPrincipal) -> dict | None:
    """The same 404 policy is applied to unknown and unauthorized claims."""
    claim = find_claim(claim_id.strip().upper())
    if not claim or not principal.groups.intersection(claim["authorized_groups"]):
        return None
    return claim


def list_documents(claim: dict, principal: VerifiedPrincipal) -> list[dict]:
    """Whitelist documents by verified role, coverage and loss date."""
    when = date.fromisoformat(claim["event_date"])
    allowed = []
    for item in catalog():
        if not principal.groups.intersection(item["allowed_groups"]):
            continue
        if item["coverage_code"] not in ("ALL", claim["coverage_code"]):
            continue
        if not date.fromisoformat(item["effective_from"]) <= when <= date.fromisoformat(item["effective_to"]):
            continue
        allowed.append({
            "document_id": item["document_id"],
            "title": item["title"],
            "filename": item["filename"],
            "format": item["path"].suffix.lower().lstrip("."),
            "version": item["version"],
            "indexed": True,
            "origin": "DOCUMENT_FICTIF",
        })
    return allowed


def get_document(claim: dict, principal: VerifiedPrincipal, document_id: str) -> dict | None:
    """Return the trusted file entry only after consulting filtered catalog."""
    if document_id not in {x["document_id"] for x in list_documents(claim, principal)}:
        return None
    return next(x for x in catalog() if x["document_id"] == document_id)
