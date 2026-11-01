"""Recherche de clauses AutoClaim - moteur local et moteur BigQuery.

Deux implementations exposent la MEME interface search(...). Le moteur local
permet les tests offline ; BigQuery est utilise pour la demonstration GCP.

SECURITE : verified_groups est issu d'une identite deja verifiee. Il ne doit
jamais etre fourni par le LLM ou directement par l'utilisateur final.
Les filtres ACL + dates s'appliquent AVANT toute restitution des clauses.
"""

from __future__ import annotations

from datetime import date
import re
import unicodedata
from typing import Any

from .repository import authorized_clauses

STOP_WORDS = {
    "a", "au", "aux", "avec", "ce", "ces", "dans", "de", "des", "du",
    "en", "est", "et", "la", "le", "les", "ou", "par", "pour", "que",
    "qui", "sur", "une", "un", "d", "l", "quelle", "quelles", "quels",
    "quel", "clause", "clauses", "contrat", "sinistre", "auto",
    # Mots reserves dans la grammaire BigQuery SEARCH.
    "and", "or", "not", "near", "in",
}

# Le nom des ressources GCP n'est jamais construit depuis une question LLM.
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def normalize(value: str) -> str:
    """Normaliser accents et casse pour un matching lexical reproducible."""
    chars = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in chars if not unicodedata.combining(char))


def _tokens(query: str) -> tuple[str, ...]:
    """Limiter et assainir les termes : aucun operateur SEARCH injecte."""
    if not isinstance(query, str) or len(query) > 300:
        raise ValueError("Question trop longue ou non textuelle")
    words = re.findall(r"[a-z0-9]+", normalize(query))
    # dict.fromkeys conserve l'ordre et supprime les doublons.
    return tuple(dict.fromkeys(w for w in words if len(w) >= 2 and w not in STOP_WORDS))[:10]


def _validate_date(event_date: str) -> date:
    """Interdire les dates absentes ou mal formees ; jamais d'acces implicite."""
    return date.fromisoformat(event_date)


def _rank(rows: list[dict[str, Any]], terms: tuple[str, ...], limit: int) -> list[dict]:
    """Trier les clauses retrouvees ; aucun score semantique n'est simule."""
    results = []
    for row in rows:
        title_tokens = set(re.findall(r"[a-z0-9]+", normalize(row["title"])))
        body_tokens = set(re.findall(r"[a-z0-9]+", normalize(row["text"])))
        query_set = set(terms)
        score = 3 * len(title_tokens & query_set) + len(body_tokens & query_set)
        if score == 0:
            continue
        # Ne restituer que les champs necessaires a la generation/citation.
        results.append({
            "clause_id": row["clause_id"],
            "document_id": row["document_id"],
            "version": row["version"],
            "section": row["section"],
            "title": row["title"],
            "coverage_code": row["coverage_code"],
            "clause_type": row["clause_type"],
            "text": row["text"],
            "citation": row["citation"],
            "score": score,
        })
    return sorted(results, key=lambda r: (-r["score"], r["citation"]))[:limit]


class LocalClauseRetriever:
    """Offline retriever, with opt-in support for the indexed demo PDF/DOCX."""

    def __init__(self, *, include_documents: bool = False):
        self.include_documents = include_documents

    def _allowed_rows(self, groups: frozenset[str], when: str) -> list[dict]:
        rows = authorized_clauses(groups, when)
        if self.include_documents:
            from .repository import ROOT
            import json
            from pathlib import Path
            index_path = ROOT / "contracts" / "ingested_documents.jsonl"
            if index_path.is_file():
                for line in index_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if (groups.intersection(item["allowed_groups"])
                        and item["effective_from"] <= when <= item["effective_to"]):
                        rows.append(item)
        return rows

    def search(
        self,
        query: str,
        *,
        verified_groups: frozenset[str],
        event_date: str,
        coverage_code: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        if not verified_groups:
            return []
        when = _validate_date(event_date)
        terms = _tokens(query)
        if limit < 1 or not terms:
            return []
        # Filtrer sur les groupes/date AVANT tout calcul de pertinence.
        clauses = self._allowed_rows(verified_groups, when.isoformat())
        if coverage_code:
            clauses = [c for c in clauses if c["coverage_code"] in (coverage_code, "ALL")]
        return _rank(clauses, terms, limit)


    def fetch_citations(
        self,
        citations: list[str],
        *,
        verified_groups: frozenset[str],
        event_date: str,
        coverage_code: str | None = None,
    ) -> list[dict]:
        """Retrouver des preuves exactes deja autorisees, sans score lexical."""
        if not verified_groups or not citations:
            return []
        if len(citations) > 20:
            raise ValueError("Trop de citations demandees")
        when = _validate_date(event_date)
        allowed = self._allowed_rows(verified_groups, when.isoformat())
        needed = set(citations)
        return [
            {
                "citation": row["citation"], "title": row["title"],
                "text": row["text"], "document_id": row["document_id"],
                "coverage_code": row["coverage_code"],
            }
            for row in allowed
            if row["citation"] in needed
            and (not coverage_code or row["coverage_code"] in (coverage_code, "ALL"))
        ]


class BigQueryClauseRetriever:
    """Recherche textuelle BigQuery SEARCH, avec ACL appliquees dans le SQL.

    L'identite GCP qui execute la requete n'est PAS l'identite metier.
    Le backend doit verifier l'identite metier et les groupes en amont.
    """

    DATASET = "autoclaim_mvp"
    TABLE = "contract_clauses_demo"

    def __init__(self, project: str, *, location: str = "europe-west1", client=None):
        if not PROJECT_RE.fullmatch(project):
            raise ValueError("Identifiant de projet GCP invalide")
        self.project = project
        self.location = location
        self.client = client  # Injection utile pour tester sans GCP.

    @property
    def table_id(self) -> str:
        return f"{self.project}.{self.DATASET}.{self.TABLE}"

    def search(
        self,
        query: str,
        *,
        verified_groups: frozenset[str],
        event_date: str,
        coverage_code: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        if not verified_groups:
            return []  # Fail closed : aucun appel BQ sans groupes verifies.
        when = _validate_date(event_date)
        terms = _tokens(query)
        if limit < 1 or not terms:
            return []

        # Import differe : les tests locaux n'ont pas besoin du SDK BigQuery.
        from google.cloud import bigquery

        if self.client is None:
            self.client = bigquery.Client(project=self.project, location=self.location)

        # IMPORTANT : SEARCH interprete les espaces comme AND par defaut.
        # Nous utilisons OR sur quelques termes normalises pour retrouver les
        # candidats, puis un score explicite en Python. Pas de recherche vectorielle.
        search_expression = " OR ".join(terms)

        # Aucun parametre de requete n'est concatene dans le SQL ; seul le nom
        # de table (valide au constructeur) est interpole en tant qu'identifiant.
        sql = f"""
            SELECT clause_id, document_id, version, section, title,
                   coverage_code, clause_type, text, citation
            FROM `{self.table_id}`
            WHERE effective_from <= @event_date
              AND effective_to >= @event_date
              AND EXISTS (
                  SELECT 1 FROM UNNEST(allowed_groups) AS allowed_group
                  WHERE allowed_group IN UNNEST(@verified_groups)
              )
              AND (@coverage_code = '' OR coverage_code IN (@coverage_code, 'ALL'))
              AND SEARCH(search_text, @search_query)
            ORDER BY clause_id
            LIMIT @candidate_limit
        """

        params = [
            bigquery.ScalarQueryParameter("event_date", "DATE", when),
            bigquery.ArrayQueryParameter("verified_groups", "STRING", sorted(verified_groups)),
            bigquery.ScalarQueryParameter("coverage_code", "STRING", coverage_code or ""),
            bigquery.ScalarQueryParameter("search_query", "STRING", search_expression),
            bigquery.ScalarQueryParameter("candidate_limit", "INT64", min(200, max(50, limit * 10))),
        ]
        job_config = bigquery.QueryJobConfig(
            query_parameters=params,
            maximum_bytes_billed=100_000_000,  # Garde-fou financier MVP.
        )
        job = self.client.query(sql, job_config=job_config, location=self.location)
        rows = [dict(row.items()) for row in job.result(timeout=60)]
        return _rank(rows, terms, limit)


    def fetch_citations(
        self,
        citations: list[str],
        *,
        verified_groups: frozenset[str],
        event_date: str,
        coverage_code: str | None = None,
    ) -> list[dict]:
        """Lire les citations EXACTES sur BigQuery, avec ACL et validite en SQL.

        Aucun appel BQ si les groupes sont absents. Une clause absente ou
        interdite ne sera jamais remplacee par une clause voisine.
        """
        if not verified_groups or not citations:
            return []
        if len(citations) > 20:
            raise ValueError("Trop de citations demandees")
        when = _validate_date(event_date)
        from google.cloud import bigquery
        if self.client is None:
            self.client = bigquery.Client(project=self.project, location=self.location)

        sql = f"""
            SELECT citation, title, text, document_id, coverage_code
            FROM `{self.table_id}`
            WHERE citation IN UNNEST(@citations)
              AND (@coverage_code = '' OR coverage_code IN (@coverage_code, 'ALL'))
              AND effective_from <= @event_date
              AND effective_to >= @event_date
              AND EXISTS (
                SELECT 1 FROM UNNEST(allowed_groups) AS allowed_group
                WHERE allowed_group IN UNNEST(@verified_groups)
              )
            ORDER BY citation
        """
        params = [
            bigquery.ArrayQueryParameter("citations", "STRING", sorted(set(citations))),
            bigquery.ScalarQueryParameter("event_date", "DATE", when),
            bigquery.ArrayQueryParameter("verified_groups", "STRING", sorted(verified_groups)),
            bigquery.ScalarQueryParameter("coverage_code", "STRING", coverage_code or ""),
        ]
        job_config = bigquery.QueryJobConfig(
            query_parameters=params,
            maximum_bytes_billed=100_000_000,
        )
        job = self.client.query(sql, job_config=job_config, location=self.location)
        return [dict(row.items()) for row in job.result(timeout=60)]
