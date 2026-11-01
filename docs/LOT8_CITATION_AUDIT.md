# Lot 8 - Reconciliation des citations du copilote

## Pourquoi ce correctif ?

La recette AutoClaim 360 a revele un decalage entre les sources citees dans la
reponse Gemini et les preuves affichees : `DEC-01` etait cite sans etre affiche,
et `CALC-01` etait affiche alors qu'il n'etait pas utilise. Ce n'etait pas une
fuite de droits, mais un defaut de traçabilite.

## Nouvelle regle du backend

Pour `POST /api/claims/{claim_id}/chat` :

1. IAP et ACL du dossier sont verifies **avant** tout acces aux donnees.
2. Le moteur deterministe et la recherche BigQuery recuperent des preuves
   applicables, en filtrant les groupes, la garantie et la date du sinistre.
3. Gemini produit sa reponse avec des identifiants de sources versionnes.
4. Le backend extrait **uniquement les references effectivement citees**.
5. Les references deja recuperees sont rapprochees; pour celles absentes, le
   backend utilise une **recherche exacte** `fetch_citations`, avec filtres
   BigQuery de groupes, garantie et date. Les liens PDF/Word sont conditionnes
   a la bibliotheque documentaire autorisee pour ce dossier.
6. Les conditions particulieres et avenants ne peuvent provenir que de la
   preanalyse structuree du SI fictif. Cas particulier : un statut
   `NOT_SUBSCRIBED` ou `OUT_OF_PERIOD` peut etre etaye par l'enregistrement de
   la police, apres controle de sa concordance avec le dossier.
7. Si une reference n'est pas verifiable, la **reponse produite par le LLM
   n'est pas retournee**. Un message neutre la remplace.
8. Si le modele ne cite aucune source, un message de demande de reformulation
   apparait, plutot que de presenter des informations metier non sourcees.

La reponse JSON expose `grounding_status` :

- `VERIFIED_CITATIONS` : toutes les references citees sont confirmees.
- `BLOCKED_UNVERIFIED_CITATION` : au moins une reference est inconnue ou refusee.
- `NO_CITATIONS` : aucune source citee.

Les evenements `citation_audit` dans Cloud Logging enregistrent uniquement ce
statut et le nombre de sources; ils n'incluent ni question, ni email, ni numero
de sinistre, ni nom de document.

**Limite importante :** la verification prouve l'existence, l'applicabilite et
l'autorisation de consultation de la reference. Elle ne prouve pas que
**chaque phrase de Gemini est semantiquement impliquee** par la source. Les
montants et les documents reçus proviennent du SI; les prescriptions
contractuelles des documents indexés. La validation humaine reste obligatoire.

## Installation PowerShell

Depuis `D:\\PROJETS\\enterprise-ai-agent-autoclaim` :

```powershell
Expand-Archive "$HOME\Downloads\autoclaim_lot8_citations.zip" -DestinationPath . -Force
uv run python -m pytest -q
```

Aucune migration BigQuery, aucun ajout de dependance et aucun changement IAM
ne sont necessaires. Le schema de la table existante contient deja les
colonnes `document_id` et `coverage_code` utilisees pour les lectures exactes.

Apres validation des tests, redeployer **le meme service** avec sa commande
`gcloud beta run deploy` existante, en conservant IAP et le compte de service.

## Recette rapide

1. Gestionnaire sur `SIN-1002` : demander « Quelles règles sur les declarations
   tardives ? ». Si Gemini cite `DEC-01`, cette reference doit apparaitre
   dans les sources verifiees. `CALC-01` ne doit pas apparaitre s'il n'est pas
   cite.
2. Gestionnaire sur `SIN-1001` : demander les justificatifs; ouvrir le PDF
   depuis la liste des sources effectivement citees.
3. Tenter `SIN-1004` depuis le gestionnaire : toujours non accessible.
4. Demander la note sensible depuis le gestionnaire : toujours absente et non
   accessible par lien direct.
5. Observer les evenements `citation_audit` dans Cloud Logging.

Le code comporte des tests de regression pour le cas `SIN-1002` et pour les
references inconnues, hors garantie ou reservees a un autre groupe.
