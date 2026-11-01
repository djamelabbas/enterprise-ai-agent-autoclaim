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
    "/", "/healthz", "/api/me",
    "/api/claims/{claim_id}/review",
    "/api/claims/{claim_id}/clauses",
    "/api/claims/{claim_id}/ask",
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
