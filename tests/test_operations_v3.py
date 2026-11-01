"""FinOps metadata and feature flags, no real cloud calls."""
import json
from fastapi.testclient import TestClient
import pytest

from autoclaim_api.app import build_app
from autoclaim_api.iap_auth import AuthenticatedUser
from autoclaim_agent.retrieval import LocalClauseRetriever
from autoclaim_api.observability import log_model_usage, log_si_connector, log_retrieval
from scripts.estimate_llm_cost import estimate
from scripts.seed_bigquery import build_rows


def test_monitored_events_do_not_contain_sensitive_data(capsys):
    log_model_usage("gemini-3.5-flash-lite", 1200, 450)
    log_si_connector(True)
    log_retrieval("hybrid", 4)
    output = capsys.readouterr().out.strip().splitlines()
    assert [json.loads(s)["event"] for s in output] == ["model_usage", "si_connector", "retrieval_search"]
    assert json.loads(output[0])["input_tokens"] == 1200
    assert "SIN-" not in str(output) and "@" not in str(output)


def test_cost_estimate_is_parameterized_not_hardcoded():
    assert estimate(1_000_000, 500_000, 0.5, 2.0) == 1.5
    with pytest.raises(ValueError): estimate(-100, 0, 1, 1)


def test_cannot_reload_only_images_discarding_documents():
    with pytest.raises(ValueError): build_rows(include_images=True)


def test_si_check_honors_server_side_acl_and_disabled_mode(monkeypatch):
    monkeypatch.setenv("AUTOCLAIM_IAP_AUDIENCE", "demo-audience")
    monkeypatch.setenv("AUTOCLAIM_MANAGER_EMAILS", "manager@example.com")
    monkeypatch.setenv("AUTOCLAIM_SI_MODE", "local")
    def verifier(*_): return AuthenticatedUser("subject", "manager@example.com")
    app = build_app(verifier=verifier, retriever_factory=LocalClauseRetriever)
    client = TestClient(app)
    assert client.get("/api/claims/SIN-1004/si-check").status_code == 404
    assert client.get("/api/claims/SIN-1001/si-check").status_code == 503
