"""API web AutoClaim protegee par IAP sur Cloud Run.

La meme identite verifiee est capturee par les outils Python et n'est
JAMAIS configurable depuis le corps de la requete ou une question LLM.
Le backend est volontairement en lecture seule (aucune indemnisation).
"""

import logging
import os
from time import perf_counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, ConfigDict, Field

from autoclaim_agent.retrieval import BigQueryClauseRetriever
from autoclaim_agent.hybrid import HybridClauseRetriever
from autoclaim_agent.si_rest import SIUnavailable, ensure_consistent, rest_enabled, make_si_connector
from autoclaim_agent.repository import list_claims
from autoclaim_agent.documents import accessible_claim, list_documents, get_document
from autoclaim_agent.security import VerifiedPrincipal
from autoclaim_agent.tools import create_tools

from .adk_runtime import answer_with_adk
from .citation_audit import audit_chat_answer
from .iap_auth import AuthenticatedUser, InvalidIdentity, verify_iap_assertion
from .observability import log_coverage_review, log_http, log_llm_call, log_citation_audit
from .roles import resolve_groups

LOG = logging.getLogger("autoclaim.api")


@dataclass(frozen=True)
class RequestContext:
    identity: AuthenticatedUser
    principal: VerifiedPrincipal


class ChatTurn(BaseModel):
    """An untrusted browser-held turn: cannot carry claims or ACL roles."""
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class ChatRequest(BaseModel):
    """Stateless multi-turn context; authorization is rechecked on EVERY turn."""
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1200)
    history: list[ChatTurn] = Field(default_factory=list, max_length=6)


class AskRequest(BaseModel):
    """Schema strict : interdit 'groups', 'role', 'email' injectes par client."""

    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=1200)


def bigquery_retriever_factory():
    """Service GCP par defaut : jamais un backend local depuis Internet."""
    project = os.environ.get("AUTOCLAIM_GCP_PROJECT", "").strip()
    if not project:
        raise RuntimeError("AUTOCLAIM_GCP_PROJECT manquant")
    location = os.environ.get("AUTOCLAIM_BIGQUERY_LOCATION", "europe-west1")
    mode = os.environ.get("AUTOCLAIM_RETRIEVAL_MODE", "lexical").strip()
    if mode == "lexical":
        return BigQueryClauseRetriever(project, location=location)
    # A separate versioned embedding table must exist before enabling.
    return HybridClauseRetriever(project, location=location, mode=mode)


def build_app(
    *,
    verifier: Callable[[str, str], AuthenticatedUser] = verify_iap_assertion,
    role_resolver: Callable[[str], frozenset[str]] = resolve_groups,
    retriever_factory: Callable = bigquery_retriever_factory,
) -> FastAPI:
    """Fabrique injectable : tests offline sans contourner la config reelle."""
    application = FastAPI(
        title="AutoClaim Coverage Copilot (MVP)",
        description="Preanalyse fictive, revue humaine obligatoire.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.middleware("http")
    async def trace_http(request: Request, call_next):
        """Journaliser toutes les requetes sans identifier les dossiers.

        En particulier, le nom de route est le template /{claim_id}
        et jamais l'URL complete contenant SIN-xxxx.
        """
        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            log_http(
                request.scope.get("route"),
                request.method,
                status_code,
                (perf_counter() - started) * 1000,
            )

    def require_context(request: Request) -> RequestContext:
        """Authentifier cryptographiquement AVANT de lire un dossier."""
        audience = os.getenv("AUTOCLAIM_IAP_AUDIENCE", "")
        if not audience:
            # Une configuration incomplete ne doit pas ouvrir l'application.
            raise HTTPException(status_code=503, detail="Authentification indisponible")

        token = request.headers.get("X-Goog-IAP-JWT-Assertion", "")
        try:
            identity = verifier(token, audience)
        except InvalidIdentity as exc:
            raise HTTPException(status_code=401, detail="Authentification requise") from exc

        # IAP identifie la personne ; l'API determine ses droits metier.
        groups = role_resolver(identity.email)
        if not groups:
            raise HTTPException(status_code=403, detail="Acces metier non autorise")
        principal = VerifiedPrincipal(subject=identity.subject, groups=groups)
        return RequestContext(identity=identity, principal=principal)

    @application.get("/healthz")
    def healthz():
        # Ne renvoie aucune information metier ni le statut des secrets.
        # IAP protege egalement cet endpoint au niveau de Cloud Run.
        return {"status": "ok"}

    @application.get("/", response_class=HTMLResponse)
    def home():
        from pathlib import Path
        return (Path(__file__).parent / "portal.html").read_text(encoding="utf-8")

    @application.get("/assets/portal.css")
    def portal_styles():
        from pathlib import Path
        return FileResponse(
            Path(__file__).parent / "portal.css", media_type="text/css",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @application.get("/assets/portal.js")
    def portal_script():
        from pathlib import Path
        return FileResponse(
            Path(__file__).parent / "portal.js", media_type="text/javascript",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @application.get("/api/me")
    def me(context: RequestContext = Depends(require_context)):
        """Permet de constater que les DEUX comptes IAP sont distincts."""
        return {
            "email": context.identity.email,
            "groups": sorted(context.principal.groups),
            "source": "verified_iap_jwt",
        }

    @application.get("/api/claims")
    def claims(context: RequestContext = Depends(require_context)):
        """Never disclose a claim without an intersection with verified roles."""
        result = []
        for claim in list_claims():
            if not context.principal.groups.intersection(claim["authorized_groups"]):
                continue
            result.append({
                "claim_id": claim["claim_id"],
                "policy_id": claim["policy_id"],
                "event_date": claim["event_date"],
                "coverage_code": claim["coverage_code"],
                "damage_eur": claim["damage_eur"],
                "description": claim["description"],
                "needs_attention": bool(claim.get("flags")),
            })
        return {"claims": result, "total": len(result)}

    @application.get("/api/claims/{claim_id}")
    def claim_summary(claim_id: str, context: RequestContext = Depends(require_context)):
        claim = accessible_claim(claim_id, context.principal)
        if claim is None:
            raise HTTPException(status_code=404, detail="Dossier indisponible")
        # Explicit allowlist: never expose underlying repository ACL metadata.
        return {
            "claim_id": claim["claim_id"],
            "policy_id": claim["policy_id"],
            "event_date": claim["event_date"],
            "coverage_code": claim["coverage_code"],
            "description": claim["description"],
            "damage_eur": claim["damage_eur"],
            "received_documents": claim.get("received_documents", []),
            "needs_attention": bool(claim.get("flags")),
            "human_validation_required": True,
        }

    @application.get("/api/claims/{claim_id}/documents")
    def claim_documents(claim_id: str, context: RequestContext = Depends(require_context)):
        claim = accessible_claim(claim_id, context.principal)
        if claim is None:
            raise HTTPException(status_code=404, detail="Dossier indisponible")
        return {"documents": list_documents(claim, context.principal)}

    @application.get("/api/claims/{claim_id}/documents/{document_id}")
    def read_document(
        claim_id: str, document_id: str, context: RequestContext = Depends(require_context)
    ):
        """A real PDF/DOCX, served only after IAP + claim + doc ACL checks."""
        claim = accessible_claim(claim_id, context.principal)
        if claim is None:
            raise HTTPException(status_code=404, detail="Dossier indisponible")
        item = get_document(claim, context.principal, document_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Document indisponible")
        suffix = item["path"].suffix.lower()
        is_pdf = suffix == ".pdf"
        is_image = suffix in {".png", ".jpg", ".jpeg"}
        return FileResponse(
            item["path"],
            media_type=(
                "application/pdf" if is_pdf else
                "image/png" if suffix == ".png" else
                "image/jpeg" if is_image else
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            filename=item["filename"],
            content_disposition_type="inline" if (is_pdf or is_image) else "attachment",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    @application.get("/api/claims/{claim_id}/review")
    def review(claim_id: str, context: RequestContext = Depends(require_context)):
        """Preambule deterministe, references BigQuery, aucune decision."""
        try:
            review_tool, _ = create_tools(context.principal, retriever_factory())
            result = review_tool(claim_id)
        except Exception:
            LOG.exception("Erreur technique de preanalyse")
            raise HTTPException(status_code=503, detail="Service indisponible")
        if result.get("status") == "NOT_ACCESSIBLE":
            # Meme statut HTTP pour identifiant inconnu et dossier interdit.
            raise HTTPException(status_code=404, detail="Dossier indisponible")
        # Journal d'activite metier minimal : sans ID sinistre ni clause.
        log_coverage_review(result)
        return result

    @application.get("/api/claims/{claim_id}/clauses")
    def clauses(
        claim_id: str,
        query: str,
        context: RequestContext = Depends(require_context),
    ):
        """Recherche de documents uniquement dans le contexte du dossier."""
        if not 2 <= len(query) <= 300:
            raise HTTPException(status_code=422, detail="Question invalide")
        try:
            _, search_tool = create_tools(context.principal, retriever_factory())
            result = search_tool(claim_id, query)
        except Exception:
            LOG.exception("Erreur technique de recherche")
            raise HTTPException(status_code=503, detail="Recherche indisponible")
        if result.get("status") == "NOT_ACCESSIBLE":
            raise HTTPException(status_code=404, detail="Dossier indisponible")
        return result

    @application.post("/api/claims/{claim_id}/ask")
    async def ask(
        claim_id: str,
        body: AskRequest,
        context: RequestContext = Depends(require_context),
    ):
        """Un appel Gemini uniquement pour un dossier deja controle.

        Les preuves indisponibles empechent tout appel LLM et toute
        suggestion de couverture. Une demande interdite reste sans cout.
        """
        try:
            retriever = retriever_factory()
            review_tool, _ = create_tools(context.principal, retriever)
            preflight = review_tool(claim_id)
        except Exception:
            LOG.exception("Erreur technique avant appel LLM")
            raise HTTPException(status_code=503, detail="Preanalyse indisponible")

        if preflight.get("status") == "NOT_ACCESSIBLE":
            raise HTTPException(status_code=404, detail="Dossier indisponible")
        if preflight.get("status") in {"EVIDENCE_UNAVAILABLE", "EVIDENCE_INCOMPLETE"}:
            raise HTTPException(status_code=503, detail="Preuves documentaires indisponibles")

        # Mesure de l'appel LLM seule, distincte du temps total de requete.
        # Ni prompt, ni reponse, ni identite ne sont conserves dans ces logs.
        started_llm = perf_counter()
        try:
            answer = await answer_with_adk(
                context.principal,
                retriever,
                claim_id,
                body.question,
            )
        except Exception:
            log_llm_call(False, (perf_counter() - started_llm) * 1000)
            LOG.exception("Erreur d'execution ADK")
            raise HTTPException(status_code=503, detail="Agent indisponible")
        log_llm_call(True, (perf_counter() - started_llm) * 1000)

        return {
            "claim_id": claim_id.upper(),
            "status": preflight["status"],
            "answer": answer,
            "source_refs": preflight.get("source_refs", []),
            "human_validation_required": True,
            "disclaimer": "Simulation fictive ; validation humaine obligatoire.",
        }

    @application.get("/api/claims/{claim_id}/si-check")
    def check_si(claim_id: str, context: RequestContext = Depends(require_context)):
        """Read-only, authenticated SI service call AFTER local business ACL.

        Even though the SI connector uses a Cloud Run service account, the
        caller's dossier authorization remains mandatory and server-enforced.
        """
        claim = accessible_claim(claim_id, context.principal)
        if claim is None:
            raise HTTPException(status_code=404, detail="Dossier indisponible")
        try:
            remote = make_si_connector().get_claim(claim["claim_id"])
            ensure_consistent(claim, remote)
        except SIUnavailable:
            from .observability import log_si_connector
            log_si_connector(False)
            raise HTTPException(status_code=503, detail="Verification SI indisponible")
        from .observability import log_si_connector
        log_si_connector(True)
        return {"status": "MATCH", "source_system": "SI_FICTIF_REST", "human_validation_required": True}

    @application.post("/api/claims/{claim_id}/chat")
    async def chat(
        claim_id: str,
        body: ChatRequest,
        context: RequestContext = Depends(require_context),
    ):
        """Conversational entry point, grounded in backend-verified evidence.

        Chat history is user-controllable and treated as untrusted text. It can
        improve continuity but NEVER provides authorization or source facts.
        Each call rechecks IAP, claim ACL, dated BigQuery evidence, and document ACL.
        """
        claim = accessible_claim(claim_id, context.principal)
        if claim is None:
            raise HTTPException(status_code=404, detail="Dossier indisponible")
        try:
            retriever = retriever_factory()
            review_tool, search_tool = create_tools(context.principal, retriever)
            preflight = review_tool(claim["claim_id"])
            if preflight.get("status") in {"EVIDENCE_UNAVAILABLE", "EVIDENCE_INCOMPLETE"}:
                raise HTTPException(status_code=503, detail="Preuves documentaires indisponibles")
            matches = search_tool(claim["claim_id"], body.question[:300])
            if matches.get("status") == "EVIDENCE_UNAVAILABLE":
                raise HTTPException(status_code=503, detail="Recherche documentaire indisponible")
        except HTTPException:
            raise
        except Exception:
            LOG.exception("Erreur technique avant conversation")
            raise HTTPException(status_code=503, detail="Recherche indisponible")

        # Optional cross-service SI verification: abort if REST differs
        # from the locally authorized claim; no silent fallback to JSON.
        verified_si_context = ""
        if rest_enabled():
            from .observability import log_si_connector
            try:
                remote = make_si_connector().get_claim(claim["claim_id"])
                consistent = ensure_consistent(claim, remote)
                verified_si_context = (
                    "\n[Contexte SI REST verifie par le backend : "
                    f"garantie={consistent['coverage_code']}, "
                    f"pieces_recues={','.join(consistent['received_documents']) or 'aucune'}, "
                    f"montant_declare={consistent['damage_eur']} EUR. "
                    "La liste des pieces recues provient du SI, pas du guide documentaire.]"
                )
                log_si_connector(True)
            except SIUnavailable:
                log_si_connector(False)
                raise HTTPException(status_code=503, detail="Verification SI indisponible")

        # The LLM is never the authority for the list of cited sources.
        # The audit after generation will reconcile each cited ID with the
        # preflight and/or an exact, ACL-filtered BigQuery lookup.

        started_llm = perf_counter()
        try:
            answer = await answer_with_adk(
                context.principal,
                retriever,
                claim["claim_id"],
                body.question + verified_si_context,
                history=[turn.model_dump() for turn in body.history],
            )
        except Exception:
            log_llm_call(False, (perf_counter() - started_llm) * 1000)
            LOG.exception("Erreur d'execution de l'agent conversationnel")
            raise HTTPException(status_code=503, detail="Agent indisponible")
        log_llm_call(True, (perf_counter() - started_llm) * 1000)

        try:
            audit = audit_chat_answer(
                answer,
                claim=claim,
                principal=context.principal,
                retriever=retriever,
                preflight=preflight,
                matches=matches,
            )
        except Exception:
            # Fail closed: an unavailable evidence lookup must never allow a
            # fabricated or unauthorized reference through to the browser.
            LOG.exception("Echec de reconciliation des citations")
            log_citation_audit("LOOKUP_UNAVAILABLE", 0)
            raise HTTPException(status_code=503, detail="Verification des sources indisponible")

        log_citation_audit(audit.status, len(audit.sources))
        return {
            "claim_id": claim["claim_id"],
            "answer": audit.answer,
            "status": preflight.get("status"),
            "sources": audit.sources,
            "grounding_status": audit.status,
            "human_validation_required": True,
            "disclaimer": "Simulation fictive. Validation humaine obligatoire.",
            "conversation_mode": "browser_context_no_server_storage",
        }

    return application


# Objet charge par Uvicorn ; aucune configuration de developpement qui
# contourne les controles d'identite en mode Cloud Run.
app = build_app()
