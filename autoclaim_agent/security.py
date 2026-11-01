"""Type de contexte d'identite recu depuis une couche de confiance.

IMPORTANT : ce module ne valide PAS les jetons Google. Pour un service web,
le backend devra construire VerifiedPrincipal APRES validation de l'identite
et resolution des groupes. Aucun groupe n'est lu depuis le texte utilisateur.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedPrincipal:
    """Contexte du demandeur, capture par les outils de son execution ADK."""

    subject: str
    groups: frozenset[str]

    def __post_init__(self) -> None:
        if not self.subject or not isinstance(self.groups, frozenset):
            raise ValueError("Identite invalide : subject et frozenset de groupes attendus")


ANONYMOUS = VerifiedPrincipal(subject="anonymous", groups=frozenset())
