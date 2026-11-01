"""Test local AutoClaim : outils d'abord, Gemini uniquement avec --execute.

AVERTISSEMENT : --simulate-group choisit un role de test. Ce script CLI
n'authentifie pas les utilisateurs et ne doit jamais etre expose via HTTP.
"""

import argparse
import asyncio
import json
import os

from autoclaim_agent.agent import create_agent
from autoclaim_agent.retrieval import BigQueryClauseRetriever, LocalClauseRetriever
from autoclaim_agent.security import VerifiedPrincipal
from autoclaim_agent.repository import find_claim
from autoclaim_agent.tools import create_tools


def build_retriever(args):
    if args.backend == "local":
        return LocalClauseRetriever()
    project = args.project or os.getenv("AUTOCLAIM_GCP_PROJECT", "")
    if not project:
        raise ValueError("--project ou AUTOCLAIM_GCP_PROJECT requis pour BigQuery")
    return BigQueryClauseRetriever(project, location=args.location)


async def ask_gemini(agent, claim_id: str, question: str, user_id: str):
    """Session ADK locale de courte duree ; a remplacer en production."""
    from google.adk.apps import App
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    app = App(name="autoclaim_local_demo", root_agent=agent)
    session_service = InMemorySessionService()
    runner = Runner(app=app, session_service=session_service)
    session = await session_service.create_session(app_name=app.name, user_id=user_id)
    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"Dossier {claim_id}. {question}")],
    )
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=message,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts or []:
                if part.text:
                    print("\nREPONSE GEMINI :\n" + part.text)


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoClaim ADK demo (non securisee)")
    parser.add_argument("--claim", default="SIN-1001")
    parser.add_argument("--query", help="Recherche libre de clauses (facultatif)")
    parser.add_argument("--backend", choices=["local", "bigquery"], default="bigquery")
    parser.add_argument("--project")
    parser.add_argument("--location", default="europe-west1")
    parser.add_argument(
        "--simulate-group", required=True,
        choices=["gestionnaires_auto", "superviseurs_auto"],
    )
    parser.add_argument("--execute", action="store_true", help="Appel Gemini payant")
    args = parser.parse_args()

    print("DEMO UNIQUEMENT : groupes simules, NON authentifies.")
    principal = VerifiedPrincipal("cli-demo", frozenset({args.simulate_group}))
    retriever = build_retriever(args)
    review_tool, search_tool = create_tools(principal, retriever)

    # Choisir une recherche adaptee au type de garantie, sans laisser le
    # modele inventer les mots-clés contractuels. Le dossier reste fictif.
    claim = find_claim(args.claim.strip().upper())
    lookup_queries = {
        "BRIS_GLACE": "bris de glace franchise plafond",
        "VOL": "vol declaration tardive",
        "DTA": "dommages tous accidents franchise plafond",
    }
    query = args.query or lookup_queries.get(
        claim["coverage_code"] if claim else None, "clause garantie"
    )

    # 1) Parcours deterministe : ACL du dossier + preuves documentaires.
    review = review_tool(args.claim)
    print("\nPREANALYSE + PREUVES :")
    print(json.dumps(review, ensure_ascii=False, indent=2))

    # 2) Recherche facultative : uniquement si le dossier est accessible.
    search = search_tool(args.claim, query)
    print("\nRECHERCHE DE CLAUSES :")
    print(json.dumps(search, ensure_ascii=False, indent=2))

    if not args.execute:
        print("\nDRY RUN : aucun appel Gemini. Ajouter --execute pour lancer ADK.")
        return

    # Aucun appel LLM si l'ACL, les preuves ou le backend sont en erreur.
    if review["status"] in {"NOT_ACCESSIBLE", "EVIDENCE_INCOMPLETE", "EVIDENCE_UNAVAILABLE"}:
        raise SystemExit("Appel Gemini bloque : dossier/preuves non accessibles.")

    print("\nAPPEL GEMINI VIA VERTEX AI (facturable)...")
    agent = create_agent(principal, retriever)
    asyncio.run(ask_gemini(agent, args.claim, query, principal.subject))


if __name__ == "__main__":
    main()
