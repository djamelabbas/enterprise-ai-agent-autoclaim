"""Resolution de roles applicatifs apres authentification IAP.

MVP : liste blanche des emails verifies dans les variables d'environnement.
Ce n'est PAS une interrogation live des groupes Cloud Identity Free.
La fonction est substituable par un futur resolver Cloud Identity / annuaire.
NE JAMAIS accepter de groupes provenant du prompt ou d'un entete HTTP.
"""

import os


MANAGER_GROUP = "gestionnaires_auto"
SUPERVISOR_GROUP = "superviseurs_auto"


def _emails(value: str) -> frozenset[str]:
    """Transformer une liste d'emails CSV en ensemble normalise."""
    return frozenset(part.strip().lower() for part in value.split(",") if part.strip())


def resolve_groups(email: str) -> frozenset[str]:
    """Renvoyer les habilitations du compte IAP ou aucune par defaut.

    Configuration dynamique : pas de secret, mais ne pas mettre les
    adresses de personnes reelles dans un depot public.
    """
    normalized = email.strip().lower()
    result = set()
    if normalized in _emails(os.getenv("AUTOCLAIM_MANAGER_EMAILS", "")):
        result.add(MANAGER_GROUP)
    if normalized in _emails(os.getenv("AUTOCLAIM_SUPERVISOR_EMAILS", "")):
        result.add(SUPERVISOR_GROUP)
    return frozenset(result)
