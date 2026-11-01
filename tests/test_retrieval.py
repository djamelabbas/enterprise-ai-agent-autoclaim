"""Tests du retrieval ACL et de la requete BigQuery (API simulee)."""

from datetime import date
import sys
import types
from unittest.mock import MagicMock

import pytest

from autoclaim_agent.retrieval import (
    BigQueryClauseRetriever,
    LocalClauseRetriever,
    normalize,
)
from autoclaim_agent.repository import list_clauses

ANALYST = frozenset({"gestionnaires_auto"})
SUPERVISOR = frozenset({"superviseurs_auto"})
WHEN = "2026-10-20"


def test_local_bris_glace_has_citation():
    matches = LocalClauseRetriever().search(
        "garantie bris de glace", verified_groups=ANALYST,
        event_date=WHEN, coverage_code="BRIS_GLACE",
    )
    assert matches[0]["clause_id"] == "BG-01"
    assert matches[0]["citation"] == "CG-AUTO-DEMO-2026@v1.0#BG-01"


def test_analyst_cannot_retrieve_supervisor_clause():
    results = LocalClauseRetriever().search(
        "note interne supervision", verified_groups=ANALYST, event_date=WHEN
    )
    assert all(row["clause_id"] != "CONF-01" for row in results)


def test_supervisor_can_retrieve_confidential_clause():
    results = LocalClauseRetriever().search(
        "note interne supervision", verified_groups=SUPERVISOR, event_date=WHEN
    )
    assert results[0]["clause_id"] == "CONF-01"


def test_missing_auth_or_expired_clauses():
    retriever = LocalClauseRetriever()
    assert retriever.search("bris glace", verified_groups=frozenset(), event_date=WHEN) == []
    assert retriever.search("bris glace", verified_groups=ANALYST, event_date="2027-01-01") == []


def test_cross_coverage_excluded():
    results = LocalClauseRetriever().search(
        "vol plainte", verified_groups=ANALYST, event_date=WHEN,
        coverage_code="BRIS_GLACE",
    )
    assert all(row["coverage_code"] in {"BRIS_GLACE", "ALL"} for row in results)


def test_no_query_tokens_fails_closed():
    retriever = LocalClauseRetriever()
    assert retriever.search("de la et un", verified_groups=ANALYST, event_date=WHEN) == []


def test_normalization_is_accent_insensitive():
    assert normalize("DÉCHÉANCE") == "decheance"


def test_bigquery_rejects_untrusted_project_id():
    with pytest.raises(ValueError):
        BigQueryClauseRetriever("abc`; DROP TABLE x")


def test_bigquery_without_verified_identity_never_calls_cloud():
    client = MagicMock()
    retriever = BigQueryClauseRetriever("test-autoclaim-123", client=client)
    assert retriever.search("bris glace", verified_groups=frozenset(), event_date=WHEN) == []
    client.query.assert_not_called()


def test_invalid_event_date_does_not_call_cloud():
    client = MagicMock()
    retriever = BigQueryClauseRetriever("test-autoclaim-123", client=client)
    with pytest.raises(ValueError):
        retriever.search("bris glace", verified_groups=ANALYST, event_date="hier")
    client.query.assert_not_called()


def test_bq_query_uses_parameterized_acl_and_search(monkeypatch):
    """Le SDK Cloud est simule ; on verifie le SQL, pas le moteur BigQuery."""
    fake = types.ModuleType("google.cloud.bigquery")

    def parameter(name, kind, value):
        return types.SimpleNamespace(name=name, kind=kind, value=value)

    fake.ScalarQueryParameter = parameter
    fake.ArrayQueryParameter = parameter
    fake.QueryJobConfig = lambda **kwargs: types.SimpleNamespace(**kwargs)
    cloud = types.ModuleType("google.cloud")
    cloud.bigquery = fake
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", fake)

    # Fausse reponse deja filtree par BigQuery. Une reponse mock ne teste pas
    # la securite reelle de la base ; nous inspectons donc aussi le SQL.
    expected = next(row for row in list_clauses() if row["clause_id"] == "BG-01")
    client = MagicMock()
    client.query.return_value.result.return_value = [expected]
    retriever = BigQueryClauseRetriever("test-autoclaim-123", client=client)
    rows = retriever.search(
        "bris de glace franchise", verified_groups=ANALYST,
        event_date=WHEN, coverage_code="BRIS_GLACE",
    )
    assert rows[0]["clause_id"] == "BG-01"
    assert rows[0]["score"] > 0

    sql = client.query.call_args.args[0]
    opts = client.query.call_args.kwargs["job_config"]
    assert "UNNEST(allowed_groups)" in sql
    assert "@verified_groups" in sql
    assert "@event_date" in sql
    assert "SEARCH(search_text, @search_query)" in sql
    assert "@coverage_code" in sql
    assert "`test-autoclaim-123.autoclaim_mvp.contract_clauses_demo`" in sql
    values = {p.name: p.value for p in opts.query_parameters}
    assert values["verified_groups"] == ["gestionnaires_auto"]
    assert values["event_date"] == date(2026, 10, 20)
    assert values["search_query"] == "bris OR glace OR franchise"
    assert opts.maximum_bytes_billed == 100_000_000
