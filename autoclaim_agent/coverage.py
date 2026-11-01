"""Moteur de PREANALYSE AutoClaim pour des donnees fictives.

La recherche de clauses sera remplacee par un vrai retriever RAG dans
le prochain lot. Le calcul monetaire reste volontairement deterministe.
Ce module n'automatise AUCUNE decision juridique ou d'indemnisation.
"""

from datetime import date

from .repository import (
    authorized_clauses,
    effective_terms,
    find_claim,
    find_policy,
)

# Prerequis documentaires simules, et non regles legales reelles.
REQUIRED_DOCUMENTS = {
    "BRIS_GLACE": ("devis_reparation",),
    "VOL": ("depot_plainte",),
    "DTA": ("constat",),
}

# Un outil LLM ne doit jamais pouvoir fournir lui-meme verified_groups.
# En production : injecter ces groupes apres validation du jeton utilisateur.
def analyze_coverage(claim_id: str, *, verified_groups: frozenset[str]) -> dict:
    """Analyser un dossier pour un utilisateur DEJA authentifie par le backend.

    Le meme statut est renvoye pour un identifiant absent ou non autorise,
    afin de ne pas permettre l'enumeration des dossiers confidentiels.
    """
    claim = find_claim(claim_id.strip().upper())
    if claim is None or not verified_groups.intersection(claim["authorized_groups"]):
        return {"status": "NOT_ACCESSIBLE", "message": "Dossier introuvable ou non autorise."}

    policy = find_policy(claim["policy_id"])
    if policy is None:
        # Un lien SI casse n'est pas synonyme de garantie non souscrite.
        return {"status": "NEEDS_REVIEW", "reason": "Contrat indisponible."}

    base = {"claim_id": claim["claim_id"], "policy_id": policy["policy_id"]}
    occurred = date.fromisoformat(claim["event_date"])
    if not (date.fromisoformat(policy["effective_from"]) <= occurred <= date.fromisoformat(policy["effective_to"])):
        return {
            **base,
            "status": "OUT_OF_PERIOD",
            "reason": "Date du sinistre hors de la periode contractuelle referencee.",
            "source_refs": [policy["conditions_particulieres_ref"]],
        }

    code = claim["coverage_code"]
    terms = effective_terms(policy, code, claim["event_date"])
    if terms is None:
        return {
            **base,
            "status": "NOT_SUBSCRIBED",
            "reason": "Garantie absente des conditions particulieres referencees.",
            "source_refs": [policy["conditions_particulieres_ref"]],
        }

    # Les clauses sont filtrees par les groupes authentifies et leur validite.
    visible = {clause["clause_id"]: clause for clause in authorized_clauses(verified_groups, claim["event_date"])}
    clause_by_coverage = {"BRIS_GLACE": "BG-01", "VOL": "VOL-01", "DTA": "DTA-01"}
    coverage_clause = clause_by_coverage.get(code)
    required_ids = (coverage_clause, "CALC-01")
    if not coverage_clause or any(clause_id not in visible for clause_id in required_ids):
        # Sans preuve contractuelle accessible, pas de calcul, meme si une
        # ligne structuree dans le SI mentionne la garantie.
        return {**base, "status": "NEEDS_REVIEW", "reason": "Clause contractuelle indisponible."}

    sources = [visible[coverage_clause]["citation"], *terms["sources"]]
    flags = set(claim["flags"])

    if "suspicion_acte_intentionnel" in flags:
        sources.append(visible["EXC-01"]["citation"])
        return {
            **base,
            "status": "EXCLUSION_REVIEW",
            "reason": "Indice d'exclusion a examiner par un gestionnaire, aucun refus automatique.",
            "source_refs": sources,
        }

    if "declaration_tardive" in flags:
        sources.append(visible["DEC-01"]["citation"])
        return {
            **base,
            "status": "DECHANCE_REVIEW",
            "reason": "Signal de retard : verifier clauses et conditions legales, sans decheance automatique.",
            "source_refs": sources,
        }

    missing_docs = sorted(set(REQUIRED_DOCUMENTS[code]) - set(claim["received_documents"]))
    if missing_docs:
        return {
            **base,
            "status": "NEEDS_DOCUMENTS",
            "missing_documents": missing_docs,
            "source_refs": sources,
        }

    # Formule de demonstration : plafond AVANT deduction de la franchise.
    # Pas de calcul confie au LLM ; montants entiers pour ce corpus demo.
    indicative = max(0, min(claim["damage_eur"], terms["limit_eur"]) - terms["deductible_eur"])
    sources.append(visible["CALC-01"]["citation"])
    return {
        **base,
        "status": "COVERED_IN_PRINCIPLE",
        "coverage_code": code,
        "deductible_eur": terms["deductible_eur"],
        "limit_eur": terms["limit_eur"],
        "indicative_amount_eur": indicative,
        "source_refs": sources,
        "human_validation_required": True,
        "disclaimer": "Simulation fictive, ni decision de couverture ni ordre d'indemnisation.",
    }
