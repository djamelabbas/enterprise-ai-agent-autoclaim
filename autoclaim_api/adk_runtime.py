"""Execution ADK a la demande, avec identite serveur non mutable.

Le Runner et la session sont recrees a chaque requete pour eviter
les contaminations entre utilisateurs et instances Cloud Run.
Ceci suffit pour une demo mono-tour ; une vraie memoire multi-tour
necessitera un service de sessions partage en V2.
"""

from autoclaim_agent.agent import create_agent
from autoclaim_agent.security import VerifiedPrincipal


async def answer_with_adk(
    principal: VerifiedPrincipal,
    retriever,
    claim_id: str,
    question: str,
) -> str:
    """Interroger Gemini apres les controles ACL effectues par l'API."""
    from google.adk.apps import App
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    agent = create_agent(principal, retriever)
    adk_app = App(name="autoclaim_secure_api", root_agent=agent)
    sessions = InMemorySessionService()
    runner = Runner(app=adk_app, session_service=sessions)
    session = await sessions.create_session(
        app_name=adk_app.name,
        user_id=principal.subject,
    )
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"Analyse uniquement {claim_id}. {question}")],
    )

    output = []
    async for event in runner.run_async(
        user_id=principal.subject,
        session_id=session.id,
        new_message=content,
    ):
        if event.is_final_response() and event.content:
            for part in event.content.parts or []:
                if part.text:
                    output.append(part.text)

    if not output:
        raise RuntimeError("Le modele n'a pas produit de reponse exploitable")
    return "\n".join(output)
