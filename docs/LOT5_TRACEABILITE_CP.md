# Lot 5 — Traçabilité des conditions particulières et des avenants

## Problème observé

Sur `SIN-1001`, le moteur calculait 80 EUR de franchise, 1 200 EUR de plafond
et 520 EUR d'indemnisation indicative, mais `contractual_evidence` ne contenait
que les conditions générales (CG) provenant de BigQuery. La référence
`CP-POL-AUTO-001@v1.0#BRIS_GLACE` apparaissait dans `source_refs` sans
justification consultable dans la réponse.

## Correctif

- `autoclaim_agent/structured_evidence.py` reconstruit la preuve **structurée**
  depuis `data/policies.json` (CP) et `data/endorsements.json` (avenant),
  avec vérification du numéro de contrat, de la garantie et de la date.
- `autoclaim_agent/tools.py` fusionne les preuves CG BigQuery et les valeurs
  CP/avenants du SI fictif. La conclusion est bloquée si **une seule**
  référence de `source_refs` manque dans `contractual_evidence`.
- Les objets de preuve indiquent `source_system` et `evidence_type`.
- `autoclaim_agent/agent.py` demande à Gemini de distinguer une clause
  documentaire d'un simple enregistrement structuré du SI.
- `tests/test_structured_evidence.py` contient sept tests supplémentaires.

## Limite importante

Ces enregistrements fictifs ne sont **pas la lecture du document original**
(CP signées ou avenant numérisé). Les montants sont justifiés par la source
structurée de démonstration, et non juridiquement établis par un document
contractuel. Une V2 devra réconcilier les données du SI avec les documents
contractuels originaux et leur historisation.

## Installation

Depuis `D:\PROJETS\enterprise-ai-agent-autoclaim` :

```powershell
Expand-Archive "$HOME\Downloads\autoclaim_lot5_traceabilite.zip" -DestinationPath . -Force
uv run python -m pytest -q
```

Attendu : **75 tests réussis** (68 existants + 7 nouveaux).

Test hors ligne :

```powershell
uv run python -c "from autoclaim_agent.tools import create_tools; from autoclaim_agent.security import VerifiedPrincipal; from autoclaim_agent.retrieval import LocalClauseRetriever; p=VerifiedPrincipal('demo', frozenset({'gestionnaires_auto'})); f,_=create_tools(p,LocalClauseRetriever()); r=f('SIN-1001'); print(r['status'], [(x['citation'],x['source_system']) for x in r['contractual_evidence']])"
```

Attendu : `COVERED_IN_PRINCIPLE` ; 2 preuves CG et 1 preuve CP (SI fictif).

## Déploiement

Après la réussite des tests, **redéployer le code** en reprenant la commande
`gcloud beta run deploy` validée au Lot 4, en conservant tous les paramètres
(`--iap`, `--no-allow-unauthenticated`, service account, variables d'environnement,
limites d'instances). Ne pas modifier les rôles IAM/IAP existants.

Recette sur Cloud Run :

1. Compte gestionnaire, `SIN-1001` -> HTTP 200, `COVERED_IN_PRINCIPLE` :
   `contractual_evidence` contient désormais `CP-POL-AUTO-001@v1.0#BRIS_GLACE`,
   avec `data.deductible_eur=80`, `data.limit_eur=1200`, `source_system=SI_FICTIF`.
2. Compte gestionnaire, `SIN-1005` -> CP initiale (plafond 8 000 EUR) +
   avenant actif (plafond 10 000 EUR), montant indicatif 9 400 EUR.
3. Compte gestionnaire, `SIN-1004` -> HTTP 404.
4. Compte superviseur, `SIN-1004` -> HTTP 200, `DECHANCE_REVIEW`.
5. Dans la réponse Gemini, toute CP doit être présentée comme issue du SI
   structuré fictif, et non comme une clause textuelle originale vérifiée.

Aucun changement de table BigQuery n'est nécessaire : les CG restent dans
BigQuery ; les CP et avenants proviennent toujours des JSON du SI fictif.

## Étapes suivantes

- Monitoring minimum (latence, erreurs, usage Gemini / BigQuery, échecs ACL)
  sans journaliser de données personnelles ni de textes contractuels sensibles.
- README d'architecture, schéma de flux, limites et instructions d'exploitation.
- Tests end-to-end documentés, GitHub Actions et publication du dépôt.
