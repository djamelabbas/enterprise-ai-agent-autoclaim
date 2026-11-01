"""Read-only Cloud Run REST connector with a Google-signed service ID token.

Authorization is always enforced by the calling FastAPI backend BEFORE the
connector is invoked. An authenticated network request is not a substitute
for dossier-level business ACL. The connector never falls back to demo JSON
when REST is configured: unexpected or inconsistent data fails closed.
"""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

CLAIM_ID_RE = re.compile(r"^SIN-[0-9]{4,8}$")

class SIUnavailable(RuntimeError):
    """Sanitized connector error; never expose network details to a user."""


def validate_service_url(url: str) -> str:
    parsed = urlsplit(url)
    # Prevent arbitrary destinations/SSRF and local bypass in the Cloud path.
    if (parsed.scheme != "https" or not parsed.hostname or
        not parsed.hostname.endswith(".run.app") or
        parsed.port is not None or parsed.username or parsed.password or
        parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("URL de service SI invalide")
    return parsed.scheme + "://" + parsed.netloc.rstrip("/")


def _id_token(audience: str) -> str:
    import google.auth.transport.requests
    import google.oauth2.id_token
    return google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), audience,
    )


def _request_json(url: str, token: str) -> dict:
    # Restrict HTTP redirects to avoid carrying the token to another host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        method="GET",
    )
    with opener.open(request, timeout=8) as response:
        if response.status != 200:
            raise SIUnavailable("SI indisponible")
        raw = response.read(8193)
    if len(raw) > 8192:
        raise SIUnavailable("Reponse SI trop volumineuse")
    return json.loads(raw)


class CloudRunSIConnector:
    def __init__(self, base_url: str, *, token_factory=None, get_json=None):
        self.base_url = validate_service_url(base_url)
        self.token_factory = token_factory or _id_token
        self.get_json = get_json or _request_json

    def get_claim(self, claim_id: str) -> dict:
        if not CLAIM_ID_RE.fullmatch(claim_id):
            raise ValueError("Identifiant de dossier invalide")
        try:
            token = self.token_factory(self.base_url)
            payload = self.get_json(f"{self.base_url}/v1/claims/{claim_id}", token)
        except Exception as exc:
            raise SIUnavailable("Connecteur SI indisponible") from exc
        if not isinstance(payload, dict) or payload.get("claim_id") != claim_id:
            raise SIUnavailable("Identite du dossier SI incoherente")
        return payload


def ensure_consistent(local: dict, remote: dict) -> dict:
    """Never use mismatched REST data to override a locally authorized claim."""
    keys = ("claim_id", "policy_id", "event_date", "coverage_code", "damage_eur")
    if not isinstance(remote, dict) or any(key not in remote for key in (*keys, "received_documents", "description")):
        raise SIUnavailable("Reponse SI incomplete")
    if not isinstance(remote["received_documents"], list) or not isinstance(remote["description"], str):
        raise SIUnavailable("Format SI inattendu")
    if any(local.get(key) != remote.get(key) for key in keys):
        raise SIUnavailable("Divergence entre les sources SI")
    if sorted(local.get("received_documents", [])) != sorted(remote.get("received_documents", [])):
        raise SIUnavailable("Divergence sur les pieces recues")
    return {key: remote[key] for key in (*keys, "received_documents", "description")}


def rest_enabled() -> bool:
    return os.environ.get("AUTOCLAIM_SI_MODE", "local") == "rest"


def make_si_connector() -> CloudRunSIConnector:
    url = os.environ.get("AUTOCLAIM_SI_URL", "").strip()
    if not rest_enabled() or not url:
        raise SIUnavailable("Connecteur REST non configure")
    return CloudRunSIConnector(url)
