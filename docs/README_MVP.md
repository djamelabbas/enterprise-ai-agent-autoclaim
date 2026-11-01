# AutoClaim - Lot 1 : donnees + moteur de preanalyse

## Objectif

Prototyper une analyse de sinistre auto sur des donnees fictives. Aucun
contrat reel, aucune decision d'indemnisation, aucune conclusion juridique.

## Contenu

- `data/policies.json` : 2 contrats fictifs et leurs garanties souscrites.
- `data/endorsements.json` : avenant modifiant le plafond DTA a une date donnee.
- `data/claims.json` : 8 scenarios, dont exclusions et decheance potentielles.
- `data/expected_cases.json` : resultats attendus pour les tests.
- `contracts/clauses.jsonl` : clauses fictives avec source/version/section/ACL.
- `autoclaim_agent/repository.py` : couche d'acces aux donnees, remplacable par API/BigQuery.
- `autoclaim_agent/coverage.py` : calcul deterministe, verification des droits de simulation.
- `tests/test_reference_data.py` : tests automatises des regles et des scenarios.

## Decisions de conception

1. Les documents contractuels et les donnees de sinistres restent separes.
2. Les avenants sont appliques selon la date de survenance du sinistre.
3. Les montants sont indicatifs, calcules en Python et non par le modele LLM.
4. La formule de cette DEMONSTRATION est `max(0, min(dommage, plafond) - franchise)`.
5. Une suspicion d'exclusion ou de decheance declenche une revue humaine.
6. Une source contractuelle est citee sous la forme `DOCUMENT@vVERSION#SECTION`.
7. Les groupes simules dans les tests ne sont PAS une authentification reelle.
8. Avant exposition par API ou outil ADK, les groupes doivent provenir d'une
   session ou d'un jeton verifie par le backend et les controles doivent
   s'appliquer avant la recherche documentaire et l'acces aux dossiers.
9. Ne jamais exposer `find_claim` ou `find_policy` directement a un agent.

## Execution (racine du projet)

```powershell
uv run python -m pytest -q
uv run python -c "from autoclaim_agent.coverage import analyze_coverage; print(analyze_coverage('SIN-1001', verified_groups=frozenset({'gestionnaires_auto'})))"
```

## Lot 2 - Apres validation

- Indexer les clauses dans BigQuery (recherche textuelle et citations).
- Exposer un outil ADK qui consulte une API de facon authentifiee.
- Tester l'acces avec les deux vrais comptes GCP par une couche IAM/IAP.
- Developper une interface de demonstration et un deploiement Cloud Run.

**Securite :** ces fichiers sont destines a un depot public uniquement tant
que toutes les donnees restent fictives. Le corpus ne constitue pas des
conditions contractuelles applicables au monde reel.
