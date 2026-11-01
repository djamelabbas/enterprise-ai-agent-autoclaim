"""Preuves structurees provenant du SI fictif (CP et avenants).

La source de verite des montants est le repertoire de contrats, PAS Gemini.
Ces lignes ne reproduisent pas de veritables documents contractuels signes :
le champ evidence_type permet de ne pas les confondre avec des clauses CG.

Un controle d'acces sur le sinistre doit etre effectue AVANT tout appel ici.
Cette fonction n'est jamais exposee directement comme outil LLM.
"""

from datetime import date

from .repository import effective_terms, find_policy, list_endorsements


def resolve_structured_evidence(claim: dict, references: list[str]) -> list[dict]:
    """Rapprocher les references CP/avenants et les enregistrements du SI.

    Retourne uniquement les references valides pour ce contrat, cette garantie
    et cette date de sinistre. Une reference absente restera absente : le code
    appelant devra bloquer la conclusion (fail closed).

    Args:
        claim: Sinistre deja autorise par le backend.
        references: Citations structurees demandees par le moteur deterministe.
    """
    if not references or len(references) > 20:
        return []

    policy = find_policy(claim["policy_id"])
    if policy is None:
        return []

    occurred = date.fromisoformat(claim["event_date"])
    if not (
        date.fromisoformat(policy["effective_from"])
        <= occurred
        <= date.fromisoformat(policy["effective_to"])
    ):
        return []

    coverage_code = claim["coverage_code"]
    base_terms = policy["coverages"].get(coverage_code)
    effective = effective_terms(policy, coverage_code, claim["event_date"])
    if base_terms is None or effective is None:
        return []

    expected_refs = set(effective["sources"])
    requested = set(references) & expected_refs

    # CP : restituer la valeur ORIGINALE, avant application des avenants.
    # Cela permet d'expliquer de maniere auditable un plafond modifie.
    cp_ref = f"{policy['conditions_particulieres_ref']}#{coverage_code}"
    records = {}
    if cp_ref in requested:
        franchise = base_terms["deductible_eur"]
        plafond = base_terms["limit_eur"]
        records[cp_ref] = {
            "citation": cp_ref,
            "title": f"Conditions particulieres - {coverage_code} (donnees SI fictives)",
            "text": (
                f"Enregistrement structure du SI fictif : garantie {coverage_code}, "
                f"franchise initiale {franchise} EUR, plafond initial {plafond} EUR. "
                "Le document contractuel original n'a pas ete consulte."
            ),
            "source_system": "SI_FICTIF",
            "evidence_type": "structured_policy_record",
            "data": {
                "policy_id": policy["policy_id"],
                "coverage_code": coverage_code,
                "deductible_eur": franchise,
                "limit_eur": plafond,
                "effective_from": policy["effective_from"],
                "effective_to": policy["effective_to"],
            },
        }

    # Avenants : seules les modifications ACTIVES a la date du sinistre
    # et deja retenues par effective_terms peuvent etre exposees.
    for amendment in list_endorsements():
        ref = amendment["citation"]
        if ref not in requested or ref == cp_ref:
            continue
        if (
            amendment["policy_id"] != policy["policy_id"]
            or amendment["coverage_code"] != coverage_code
            or amendment["status"] != "active"
            or date.fromisoformat(amendment["effective_from"]) > occurred
        ):
            continue
        changes = amendment["changes"]
        summary = ", ".join(f"{key}={value}" for key, value in sorted(changes.items()))
        records[ref] = {
            "citation": ref,
            "title": f"Avenant {amendment['endorsement_id']} (donnees SI fictives)",
            "text": (
                f"Enregistrement structure du SI fictif, applicable depuis "
                f"{amendment['effective_from']} : {summary}. "
                "Le document contractuel original n'a pas ete consulte."
            ),
            "source_system": "SI_FICTIF",
            "evidence_type": "structured_endorsement_record",
            "data": {
                "policy_id": amendment["policy_id"],
                "coverage_code": coverage_code,
                "effective_from": amendment["effective_from"],
                "changes": dict(changes),
            },
        }

    # Respecter l'ordre des citations demandees pour faciliter l'audit.
    return [records[ref] for ref in references if ref in records]
