"""Deterministic, fail-closed citation reconciliation for the AutoClaim chat.

The LLM is NOT trusted to decide which references it may cite. A reference
shown to the user must be traceable to a source independently authorized by
the backend for the verified IAP principal, the claim, and the loss date.

Important limitation: validating a citation's existence does NOT prove that
an arbitrary sentence is entailed by that source. Human review remains
mandatory; claim-level semantic validation requires a separate evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from autoclaim_agent.documents import list_documents
from autoclaim_agent.repository import find_policy
from autoclaim_agent.security import VerifiedPrincipal

# Require the complete, versioned citation identifier used by our index.
# A reference to a nonexistent or unauthorized item is never printed back.
CITATION_RE = re.compile(
    r"(?<![\w-])(?:CG|DOC|CP|AV)-[A-Z0-9-]{3,90}@v[0-9]+(?:\.[0-9]+)*(?:#[A-Z0-9_-]{1,40})?"
)
DOC_ID_RE = re.compile(r"(?<![\w-])DOC-[A-Z0-9]+(?:-[A-Z0-9]+)*(?![\w-])")
MAX_CITATIONS = 12

SAFE_ANSWER = (
    "Je ne peux pas fournir cette reponse : une ou plusieurs references "
    "ne sont pas verifiables dans les sources autorisees pour ce dossier. "
    "Aucune conclusion ne doit etre tiree sans verification humaine."
)
NO_SOURCE_ANSWER = (
    "Je ne peux pas fournir une reponse metier justifiee sans citer au moins "
    "une source verifiable. Reformulez la question ou demandez une revue humaine."
)


@dataclass(frozen=True)
class CitationAudit:
    answer: str
    sources: list[dict]
    status: str


def extract_citations(answer: str) -> list[str]:
    """Extract only full, versioned IDs; preserve the order of first mention."""
    return list(dict.fromkeys(CITATION_RE.findall(answer)))


def _reference_from_evidence(row: dict, *, allowed_docs: dict[str, dict]) -> dict | None:
    """Normalize only records already authorized by a backend retrieval."""
    citation = row.get("citation", "")
    if not CITATION_RE.fullmatch(citation):
        return None
    document_id = row.get("document_id")
    if citation.startswith("DOC-"):
        # Refuse a document even if a misconfigured search returned its row.
        declared_id = citation.split("@", 1)[0]
        if document_id != declared_id or document_id not in allowed_docs:
            return None
        doc = allowed_docs[document_id]
        return {
            "citation": citation,
            "title": row["title"],
            "excerpt": row["text"][:1100],
            "origin": "DOCUMENT_PDF_DOCX",
            "document_id": document_id,
            "format": doc["format"],
        }

    # Only contractual clauses can originate from the documentary retriever.
    if citation.startswith("CG-"):
        return {
            "citation": citation,
            "title": row["title"],
            "excerpt": row["text"][:1100],
            "origin": "BIGQUERY",
        }
    return None


def _structured_preflight_source(row: dict) -> dict | None:
    """Structured CP/endorsement sources must come from the reviewed SI result."""
    citation = row.get("citation", "")
    if not CITATION_RE.fullmatch(citation):
        return None
    if citation.startswith(("CP-", "AV-")) and row.get("source_system") == "SI_FICTIF":
        return {
            "citation": citation,
            "title": row["title"],
            "excerpt": row["text"][:1100],
            "origin": "SI_FICTIF",
        }
    return None


def _absence_or_period_source(claim: dict, preflight: dict, citation: str) -> dict | None:
    """Reference non-subscription/period status to the authorized policy SI.

    For NOT_SUBSCRIBED, the pre-analysis does not produce a CP coverage record,
    because that coverage does not exist. We can still verify the *absence*
    directly in the fictional policy data, without inventing a signed clause.
    """
    if preflight.get("status") not in {"NOT_SUBSCRIBED", "OUT_OF_PERIOD"}:
        return None
    policy = find_policy(claim["policy_id"])
    if not policy or citation != policy["conditions_particulieres_ref"]:
        return None
    if citation not in preflight.get("source_refs", []):
        return None
    when = claim["event_date"]
    if preflight["status"] == "NOT_SUBSCRIBED":
        if claim["coverage_code"] in policy["coverages"]:
            return None
        details = (
            f"Selon les donnees structurees du SI fictif, la garantie "
            f"{claim['coverage_code']} ne figure pas dans la liste des garanties "
            "de cette police. L'original contractuel signe n'a pas ete consulte."
        )
    else:
        if policy["effective_from"] <= when <= policy["effective_to"]:
            return None
        details = (
            f"Le SI fictif indique une validite du {policy['effective_from']} "
            f"au {policy['effective_to']}, distincte de la date du sinistre. "
            "L'original contractuel signe n'a pas ete consulte."
        )
    return {
        "citation": citation,
        "title": "Conditions particulieres - enregistrement SI fictif",
        "excerpt": details,
        "origin": "SI_FICTIF",
    }


def audit_chat_answer(
    answer: str,
    *,
    claim: dict,
    principal: VerifiedPrincipal,
    retriever,
    preflight: dict,
    matches: dict,
) -> CitationAudit:
    """Allow only sources cited in the answer AND verified for this principal.

    Raises if the exact retrieval is technically unavailable: the caller must
    return an error, never silently accept a generated reference.
    """
    citations = extract_citations(answer)
    if not citations:
        return CitationAudit(NO_SOURCE_ANSWER, [], "NO_CITATIONS")
    if len(citations) > MAX_CITATIONS:
        return CitationAudit(SAFE_ANSWER, [], "BLOCKED_UNVERIFIED_CITATION")

    allowed_docs = {d["document_id"]: d for d in list_documents(claim, principal)}
    # Catch bare/partial document identifiers, too. An LLM cannot include an
    # unauthorized document ID in prose and evade the full-citation check.
    if any(doc_id not in allowed_docs for doc_id in DOC_ID_RE.findall(answer)):
        return CitationAudit(SAFE_ANSWER, [], "BLOCKED_UNVERIFIED_CITATION")

    evidence: dict[str, dict] = {}

    # 1) Sources that the deterministic coverage tool already verified.
    for row in preflight.get("contractual_evidence", []):
        reference = _structured_preflight_source(row)
        if reference is None and row.get("citation", "").startswith("CG-"):
            reference = _reference_from_evidence(row, allowed_docs=allowed_docs)
        if reference is not None:
            evidence[reference["citation"]] = reference

    # 2) Lexical search from BigQuery (already filtered by identity/date/cover).
    for row in matches.get("clauses", []):
        if row.get("coverage_code") not in (claim["coverage_code"], "ALL"):
            continue
        reference = _reference_from_evidence(row, allowed_docs=allowed_docs)
        if reference is not None:
            evidence[reference["citation"]] = reference

    # 3) Explicitly requested-by-model references: exact lookup in BigQuery,
    # still subject to SQL ACL, validity date and coverage constraints.
    missing = [ref for ref in citations if ref not in evidence]
    for ref in missing:
        if ref.startswith("CP-"):
            item = _absence_or_period_source(claim, preflight, ref)
            if item is not None:
                evidence[ref] = item

    missing_documentary = [
        ref for ref in citations if ref not in evidence and ref.startswith(("CG-", "DOC-"))
    ]
    if missing_documentary:
        found = retriever.fetch_citations(
            missing_documentary,
            verified_groups=principal.groups,
            event_date=claim["event_date"],
            coverage_code=claim["coverage_code"],
        )
        for row in found:
            if row.get("citation") not in missing_documentary:
                continue
            if row.get("coverage_code") not in (claim["coverage_code"], "ALL"):
                continue
            reference = _reference_from_evidence(row, allowed_docs=allowed_docs)
            if reference is not None:
                evidence[reference["citation"]] = reference

    # Any unsupported citation invalidates the entire generated answer.
    # This is intentionally stricter than simply deleting a bad citation:
    # deleting it could leave behind a false or confidential assertion.
    if any(ref not in evidence for ref in citations):
        return CitationAudit(SAFE_ANSWER, [], "BLOCKED_UNVERIFIED_CITATION")
    return CitationAudit(answer, [evidence[ref] for ref in citations], "VERIFIED_CITATIONS")
