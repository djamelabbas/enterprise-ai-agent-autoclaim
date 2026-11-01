"""Acces aux donnees de demonstration AutoClaim.

Les donnees sont stockees dans des fichiers uniquement pour le MVP.
Ce module definit une interface simple qu'on pourra ensuite adapter
vers BigQuery ou un SI expose via une API REST.

IMPORTANT : les fonctions de ce module ne constituent pas un controle
d'acces. Aucune fonction de lecture brute ne doit etre exposee
comme outil ADK accessible directement par un utilisateur.
"""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read_json(relative_path: str):
    """Charger un fichier de donnees depuis la racine du projet."""
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def list_policies() -> list[dict]:
    return _read_json("data/policies.json")


def list_claims() -> list[dict]:
    return _read_json("data/claims.json")


def list_endorsements() -> list[dict]:
    return _read_json("data/endorsements.json")


def list_clauses() -> list[dict]:
    path = ROOT / "contracts/clauses.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def find_policy(policy_id: str) -> dict | None:
    """Lecture interne uniquement : pas de garantie de securite ici."""
    return next((p for p in list_policies() if p["policy_id"] == policy_id), None)


def find_claim(claim_id: str) -> dict | None:
    """Lecture interne uniquement : utiliser l'analyse autorisee cote API."""
    return next((c for c in list_claims() if c["claim_id"] == claim_id), None)


def effective_terms(policy: dict, coverage_code: str, event_date: str) -> dict | None:
    """Appliquer uniquement les avenants deja actifs a la date du sinistre.

    Cette regle evite d'appliquer retroactivement une modification du contrat.
    """
    original = policy["coverages"].get(coverage_code)
    if original is None:
        return None

    terms = deepcopy(original)
    terms["sources"] = [f"{policy['conditions_particulieres_ref']}#{coverage_code}"]

    amendments = sorted(
        (
            a for a in list_endorsements()
            if a["status"] == "active"
            and a["policy_id"] == policy["policy_id"]
            and a["coverage_code"] == coverage_code
            and date.fromisoformat(a["effective_from"]) <= date.fromisoformat(event_date)
        ),
        key=lambda a: (a["effective_from"], a["endorsement_id"]),
    )

    for amendment in amendments:
        terms.update(amendment["changes"])
        terms["sources"].append(amendment["citation"])

    return terms


def authorized_clauses(verified_groups: frozenset[str], event_date: str) -> list[dict]:
    """Filtrer les clauses AVANT toute restitution ou recherche RAG.

    verified_groups doit provenir d'une couche d'authentification de confiance
    (IAM / IAP / verification backend), jamais du prompt de l'utilisateur.
    """
    if not verified_groups:
        return []

    when = date.fromisoformat(event_date)
    return [
        clause for clause in list_clauses()
        if verified_groups.intersection(clause["allowed_groups"])
        and date.fromisoformat(clause["effective_from"]) <= when
        <= date.fromisoformat(clause["effective_to"])
    ]
