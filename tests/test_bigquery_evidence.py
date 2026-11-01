"""Vise a tester les garde-fous SQL, pas les ACL Google reelles."""

from datetime import date
from types import SimpleNamespace, ModuleType
from unittest.mock import MagicMock
import sys

from autoclaim_agent.retrieval import BigQueryClauseRetriever


def test_fetch_citations_no_groups_skips_bigquery():
    fake_client = MagicMock()
    retriever = BigQueryClauseRetriever("test-autoclaim-123", client=fake_client)
    assert retriever.fetch_citations(["CG-X"], verified_groups=frozenset(), event_date="2026-10-20") == []
    fake_client.query.assert_not_called()


def test_fetch_citations_uses_sql_parameters_and_acl(monkeypatch):
    fake = ModuleType("google.cloud.bigquery")
    fake.ArrayQueryParameter = lambda name, kind, value: SimpleNamespace(name=name, kind=kind, value=value)
    fake.ScalarQueryParameter = fake.ArrayQueryParameter
    fake.QueryJobConfig = lambda **kwargs: SimpleNamespace(**kwargs)
    cloud = ModuleType("google.cloud")
    cloud.bigquery = fake
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", fake)

    fake_client = MagicMock()
    fake_client.query.return_value.result.return_value = [{
        "citation": "CG-AUTO-DEMO-2026@v1.0#BG-01",
        "title": "Bris de glace",
        "text": "Texte contractuel fictif",
    }]
    retriever = BigQueryClauseRetriever("test-autoclaim-123", client=fake_client)
    refs = ["CG-AUTO-DEMO-2026@v1.0#BG-01"]
    result = retriever.fetch_citations(
        refs,
        verified_groups=frozenset({"gestionnaires_auto"}),
        event_date="2026-10-20",
    )
    assert len(result) == 1
    sql = fake_client.query.call_args.args[0]
    params = fake_client.query.call_args.kwargs["job_config"].query_parameters
    values = {item.name: item.value for item in params}
    assert "citation IN UNNEST(@citations)" in sql
    assert "UNNEST(allowed_groups)" in sql
    assert "@verified_groups" in sql
    assert "effective_to >= @event_date" in sql
    assert values["citations"] == refs
    assert values["verified_groups"] == ["gestionnaires_auto"]
    assert values["event_date"] == date(2026, 10, 20)
    assert fake_client.query.call_args.kwargs["job_config"].maximum_bytes_billed == 100_000_000
