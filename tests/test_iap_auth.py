"""Verifier les claims IAP sans contacter Google, via mock CRYPTO uniquement."""

from datetime import datetime, timezone

import pytest

from autoclaim_api import iap_auth
from autoclaim_api.roles import resolve_groups

AUD = "/projects/123456789/locations/europe-west1/services/autoclaim-mvp"


def fake_claims(**overrides):
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "iss": "https://cloud.google.com/iap", "aud": AUD,
        "iat": now - 10, "exp": now + 300,
        "sub": "google-sub-001", "email": "MANAGER@EXAMPLE.COM",
    }
    claims.update(overrides)
    return claims


def test_verified_iap_claims_pass(monkeypatch):
    monkeypatch.setattr(iap_auth, "_verify_signature", lambda token, audience: fake_claims())
    user = iap_auth.verify_iap_assertion("signed-token", AUD)
    assert user.subject == "google-sub-001"
    assert user.email == "manager@example.com"


@pytest.mark.parametrize("change", [
    {"iss": "attacker"},
    {"aud": "/projects/other/locations/europe-west1/services/autoclaim-mvp"},
    {"email": ""},
    {"sub": ""},
    {"iat": 9999999999},
    {"exp": 1},
])
def test_incorrect_claims_denied(monkeypatch, change):
    monkeypatch.setattr(
        iap_auth, "_verify_signature", lambda token, audience: fake_claims(**change)
    )
    with pytest.raises(iap_auth.InvalidIdentity):
        iap_auth.verify_iap_assertion("signed-token", AUD)


def test_signature_verification_failure_denied(monkeypatch):
    def fail(*args):
        raise ValueError("invalid signature")
    monkeypatch.setattr(iap_auth, "_verify_signature", fail)
    with pytest.raises(iap_auth.InvalidIdentity, match="verification"):
        iap_auth.verify_iap_assertion("tampered", AUD)


def test_missing_jwt_denied_even_if_claims_would_be_valid(monkeypatch):
    monkeypatch.setattr(iap_auth, "_verify_signature", lambda *args: fake_claims())
    with pytest.raises(iap_auth.InvalidIdentity):
        iap_auth.verify_iap_assertion("", AUD)


def test_roles_default_deny_and_two_profiles(monkeypatch):
    monkeypatch.setenv("AUTOCLAIM_MANAGER_EMAILS", "manager@example.com")
    monkeypatch.setenv("AUTOCLAIM_SUPERVISOR_EMAILS", "supervisor@example.com")
    assert resolve_groups("UNKNOWN@example.com") == frozenset()
    assert resolve_groups("manager@example.com") == frozenset({"gestionnaires_auto"})
    assert resolve_groups("supervisor@example.com") == frozenset({"superviseurs_auto"})
