"""Verification de l'identite IAP.

SECURITE : seul X-Goog-IAP-JWT-Assertion signe est accepte.
Les entetes X-Goog-Authenticated-User-* non signes sont ignores.
Cette verification est obligatoire meme si Cloud Run active IAP.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

IAP_ISSUER = "https://cloud.google.com/iap"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"


class InvalidIdentity(Exception):
    """Jeton IAP absent, non verifie ou invalide."""


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identite issue d'un JWT IAP dont la signature a ete verifiee."""

    subject: str
    email: str


def _verify_signature(token: str, audience: str) -> dict:
    """Verifier cryptographiquement le JWT avec les cles PUBLIQUES IAP.

    google-auth controle la signature, l'audience et les timestamps.
    Il utilise les cles propres a IAP (pas celles des ID tokens OAuth).
    """
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    return id_token.verify_token(
        token,
        Request(),
        audience=audience,
        certs_url=IAP_CERTS_URL,
    )


def verify_iap_assertion(token: str, audience: str) -> AuthenticatedUser:
    """Convertir un JWT IAP valide en identite applicative fiable.

    Le backend DOIT connaitre l'audience attendue a partir du projet,
    de la region et du nom du service Cloud Run. Fail-closed sinon.
    """
    if not token or not audience or not audience.startswith("/projects/"):
        raise InvalidIdentity("Assertion IAP ou audience manquante")

    try:
        claims = _verify_signature(token, audience)
    except Exception as exc:
        # Ne jamais mettre le JWT ou son contenu dans les logs.
        raise InvalidIdentity("Echec de verification IAP") from exc

    now = datetime.now(timezone.utc).timestamp()
    try:
        issued = int(claims["iat"])
        expires = int(claims["exp"])
        issuer = claims["iss"]
        token_audience = claims["aud"]
        subject = claims["sub"]
        email = claims["email"].strip().lower()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise InvalidIdentity("Claims d'identite incomplets") from exc

    # Verification explicite : defense en profondeur et anti-rejeu.
    if (
        issuer != IAP_ISSUER
        or token_audience != audience
        or not subject
        or not email
        or "@" not in email
        or issued > now + 30
        or expires <= now - 30
        or expires - issued > 660
        or issued > expires
    ):
        raise InvalidIdentity("Claims IAP invalides")

    return AuthenticatedUser(subject=subject, email=email)
