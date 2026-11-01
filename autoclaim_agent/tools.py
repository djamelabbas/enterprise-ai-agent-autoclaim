"""Outils ADK relies au SI local et au retrieval BigQuery.

SECURITE : create_tools capture le principal transmis par le backend.
Le modele ne recoit que les parametres fonctionnels (claim_id, query) :
aucun argument groups, identity ou role n'est expose au LLM.

La version CLI permet de SIMULER un principal de test ; cette simulation
n'est pas une authentification et ne doit jamais etre mise en ligne.
"""

import logging

from .coverage import analyze_coverage
from .repository import find_claim
from .retrieval import LocalClauseRetriever
from .security import VerifiedPrincipal
from .structured_evidence import resolve_structured_evidence

LOGGER = logging.getLogger(__name__)
DENIED = {"status": "NOT_ACCESSIBLE", "message": "Dossier introuvable ou non autorise."}


def create_tools(principal: VerifiedPrincipal, retriever=None):
    """Construire les deux outils avec le principal de cette execution.

    Args:
        principal: Identite deja verifiee par l'appelant serveur.
        retriever: Adaptateur interchangeable (BigQuery ou local pour tests).
    """
    if not isinstance(principal, VerifiedPrincipal):
        raise TypeError("VerifiedPrincipal requis")
    if retriever is None:
        retriever = LocalClauseRetriever()

    def prepare_coverage_review(claim_id: str) -> dict:
        """Prepare une preanalyse de couverture d'un sinistre auto fictif.

        Le resultat ne constitue jamais une decision d'indemnisation.
        Les preuves CG doivent aussi etre presentes dans le retriever.

        Args:
            claim_id: Identifiant du sinistre, exemple SIN-1001.
        """
        result = analyze_coverage(claim_id, verified_groups=principal.groups)
        if result["status"] in {
            "NOT_ACCESSIBLE", "OUT_OF_PERIOD", "NOT_SUBSCRIBED", "NEEDS_REVIEW",
        }:
            # Aucun document RAG requis pour une absence de garantie en CP,
            # une date hors contrat ou un refus d'acces.
            return result

        # Les CG sont dans BigQuery ; les CP/avenants restent dans le SI mock.
        # Exiger la preuve CG exacte pour eviter des citations fictives.
        cg_refs = sorted({
            ref for ref in result.get("source_refs", [])
            if ref.startswith("CG-AUTO-DEMO-")
        })
        if not cg_refs:
            return result

        claim = find_claim(claim_id.strip().upper())
        if claim is None or not principal.groups.intersection(claim["authorized_groups"]):
            return dict(DENIED)

        try:
            clauses = retriever.fetch_citations(
                cg_refs,
                verified_groups=principal.groups,
                event_date=claim["event_date"],
            )
        except Exception:
            # Pas de repli silencieux sur une autre base documentaire.
            LOGGER.exception("Retrieval contractuel indisponible")
            return {
                "status": "EVIDENCE_UNAVAILABLE",
                "claim_id": claim["claim_id"],
                "message": "Preuves contractuelles indisponibles, examen humain requis.",
                "human_validation_required": True,
            }

        # La CG est stockee en base documentaire. Les CP et avenants, eux,
        # proviennent du SI fictif : les deux types de preuves sont DIFFERENTS.
        # Aucune source n'est consideree verifiee au seul motif que son ID est
        # present dans source_refs.
        structured_refs = [ref for ref in result["source_refs"] if ref not in cg_refs]
        try:
            structured = resolve_structured_evidence(claim, structured_refs)
        except Exception:
            LOGGER.exception("Lecture des conditions particulieres indisponible")
            return {
                "status": "EVIDENCE_UNAVAILABLE",
                "claim_id": claim["claim_id"],
                "message": "Preuves SI indisponibles, examen humain requis.",
                "human_validation_required": True,
            }

        cg_evidence = [
            {
                "citation": clause["citation"],
                "title": clause["title"],
                "text": clause["text"],
                "source_system": (
                    "BIGQUERY" if retriever.__class__.__name__ == "BigQueryClauseRetriever"
                    else "DOCUMENT_LOCAL_DEMO"
                ),
                "evidence_type": "documentary_clause",
            }
            for clause in clauses
        ]
        evidence = cg_evidence + structured

        # Les sources doivent TOUTES etre resolues et documentees.
        # Si l'une manque (CP, avenant ou CG), la conclusion est bloquee.
        found = {item["citation"] for item in evidence}
        missing = sorted(set(result["source_refs"]) - found)
        if missing:
            return {
                "status": "EVIDENCE_INCOMPLETE",
                "claim_id": claim["claim_id"],
                "message": "Preuves contractuelles incompletes, examen humain requis.",
                "missing_citations": missing,
                "human_validation_required": True,
            }

        return {
            **result,
            "contractual_evidence": evidence,
            "evidence_origin": "BIGQUERY_ET_SI_FICTIF" if cg_evidence[0]["source_system"] == "BIGQUERY" else "LOCAL_ET_SI_FICTIF",
        }

    def search_contract_clauses(claim_id: str, query: str) -> dict:
        """Recherche les clauses documentaires applicables au sinistre.

        Le controle du dossier precede TOUJOURS l'appel BigQuery.

        Args:
            claim_id: Identifiant du sinistre, exemple SIN-1001.
            query: Question de recherche contractuelle, sans identite ni role.
        """
        claim = find_claim(claim_id.strip().upper())
        if claim is None or not principal.groups.intersection(claim["authorized_groups"]):
            return dict(DENIED)
        try:
            clauses = retriever.search(
                query,
                verified_groups=principal.groups,
                event_date=claim["event_date"],
                coverage_code=claim["coverage_code"],
                limit=5,
            )
        except Exception:
            LOGGER.exception("Recherche contractuelle indisponible")
            return {
                "status": "EVIDENCE_UNAVAILABLE",
                "message": "Recherche contractuelle indisponible.",
            }
        return {
            "status": "OK" if clauses else "NO_MATCH",
            "claim_id": claim["claim_id"],
            "clauses": clauses,
        }

    return prepare_coverage_review, search_contract_clauses
