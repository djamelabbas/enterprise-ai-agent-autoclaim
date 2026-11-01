"""Journalisation structuree minimale du MVP AutoClaim.

Les journaux sont envoyes sur stdout : Cloud Run les transfere automatiquement
vers Cloud Logging (jsonPayload). On journalise UNIQUEMENT des metadonnees
techniques autorisees. Aucune identite, ID de sinistre, requete LLM, clause,
JWT, montant, ou document contractuel n'est inscrit dans les logs.

Ce module ne remplace pas une plateforme de traces distribuees. Le suivi
fin des tokens et couts Gemini est une evolution ulterieure.
"""

import json
import sys

# Liste positive des chemins HTTP : ne jamais journaliser le chemin brut,
# car il contient des identifiants de sinistres (ex. SIN-1001).
OPERATIONS = frozenset({
    "/", "/healthz", "/api/me", "/assets/portal.css", "/assets/portal.js",
    "/api/claims/{claim_id}/review",
    "/api/claims/{claim_id}/clauses",
    "/api/claims/{claim_id}/ask",
    "/api/claims",
    "/api/claims/{claim_id}",
    "/api/claims/{claim_id}/documents",
    "/api/claims/{claim_id}/documents/{document_id}",
    "/api/claims/{claim_id}/chat",
    "/api/claims/{claim_id}/si-check",
})

# Les statuts fonctionnels sont volontairement bornes a des valeurs connues.
# On evite de propager du texte produit par un document ou un modele dans les logs.
OUTCOMES = frozenset({
    "COVERED_IN_PRINCIPLE", "DECHANCE_REVIEW", "EXCLUSION_REVIEW",
    "NOT_SUBSCRIBED", "OUT_OF_PERIOD", "NEEDS_REVIEW",
    "EVIDENCE_INCOMPLETE", "EVIDENCE_UNAVAILABLE",
})
EVIDENCE_ORIGINS = frozenset({
    "BIGQUERY_ET_SI_FICTIF", "BIGQUERY", "SI_FICTIF", "LOCAL",
})


def _emit(event: str, severity: str, **fields) -> None:
    """Un JSON par ligne ; Cloud Logging l'indexera comme jsonPayload."""
    payload = {
        "severity": severity,
        "message": "AutoClaim telemetry",
        "event": event,
        "component": "autoclaim-api",
        **fields,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def log_http(route, method: str, status_code: int, duration_ms: float) -> None:
    """Journaliser le point d'entree HTTP, sans URL, query-string ou email."""
    operation = getattr(route, "path", None)
    if operation not in OPERATIONS:
        operation = "unmatched"
    safe_method = method if method in {"GET", "POST"} else "OTHER"
    _emit(
        "http_request",
        "WARNING" if status_code >= 400 else "INFO",
        operation=operation,
        method=safe_method,
        status_code=int(status_code),
        duration_ms=round(max(0.0, duration_ms), 1),
    )


def log_coverage_review(result: dict) -> None:
    """Suivre une preanalyse sans donner acces aux donnees contractuelles."""
    outcome = result.get("status")
    origin = result.get("evidence_origin")
    _emit(
        "coverage_review",
        "WARNING" if outcome in {"EVIDENCE_UNAVAILABLE", "EVIDENCE_INCOMPLETE"} else "INFO",
        outcome=outcome if outcome in OUTCOMES else "OTHER",
        evidence_origin=origin if origin in EVIDENCE_ORIGINS else "UNSPECIFIED",
        human_validation_required=bool(result.get("human_validation_required", True)),
    )


def log_llm_call(succeeded: bool, duration_ms: float) -> None:
    """Tracer succes/echec et duree des appels ADK, sans prompt ni reponse."""
    _emit(
        "llm_call",
        "INFO" if succeeded else "ERROR",
        outcome="success" if succeeded else "error",
        duration_ms=round(max(0.0, duration_ms), 1),
    )


# No reference identifiers or model text in telemetry: only a bounded status
# and source count can be emitted to Cloud Logging.
GROUNDING_STATUSES = frozenset({
    "VERIFIED_CITATIONS", "BLOCKED_UNVERIFIED_CITATION",
    "NO_CITATIONS", "LOOKUP_UNAVAILABLE",
})


def log_citation_audit(status: str, source_count: int) -> None:
    """Trace whether source reconciliation passed, without any citations."""
    safe_status = status if status in GROUNDING_STATUSES else "OTHER"
    _emit(
        "citation_audit",
        "INFO" if safe_status == "VERIFIED_CITATIONS" else "WARNING",
        outcome=safe_status,
        verified_source_count=max(0, min(12, int(source_count))),
    )


# Operational events are deliberately metadata-only; no user IDs or prompts.
RETRIEVAL_MODES = frozenset({"hybrid", "semantic", "lexical_fallback"})


def log_retrieval(mode: str, retrieved_count: int) -> None:
    _emit("retrieval_search", "WARNING" if mode == "lexical_fallback" else "INFO",
          mode=mode if mode in RETRIEVAL_MODES else "OTHER",
          result_count=max(0, min(20, int(retrieved_count))))


def log_si_connector(succeeded: bool) -> None:
    _emit("si_connector", "INFO" if succeeded else "WARNING",
          outcome="match" if succeeded else "error")


def log_model_usage(model: str, input_tokens: int, output_tokens: int) -> None:
    """Token volume is measurable; monetary cost comes from current SKU billing."""
    safe_model = model if model in {"gemini-3.5-flash-lite", "gemini-3.5-flash"} else "OTHER"
    _emit("model_usage", "INFO", model=safe_model,
          input_tokens=max(0, min(int(input_tokens), 1_000_000)),
          output_tokens=max(0, min(int(output_tokens), 1_000_000)))
