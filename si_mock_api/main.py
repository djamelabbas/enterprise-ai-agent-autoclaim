"""Separate fictional claim SI. Deploy as a PRIVATE Cloud Run service.

Network reachability is NOT authorization. Cloud Run IAM must permit only
AutoClaim's runtime service account to invoke this API. Do NOT enable allUsers.
"""
import json
from functools import lru_cache
from pathlib import Path
from fastapi import FastAPI, HTTPException

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

@lru_cache(maxsize=1)
def data():
    return json.loads((Path(__file__).parent / "claims.json").read_text(encoding="utf-8"))

@app.get("/healthz")
def health():
    return {"status": "ok"}

@app.get("/v1/claims/{claim_id}")
def read_claim(claim_id: str):
    """No document/authorization group metadata exposed by this mock."""
    for claim in data():
        if claim["claim_id"] == claim_id:
            keys = ("claim_id", "policy_id", "event_date", "coverage_code", "damage_eur", "received_documents", "description")
            return {key: claim[key] for key in keys}
    raise HTTPException(status_code=404, detail="Dossier indisponible")
