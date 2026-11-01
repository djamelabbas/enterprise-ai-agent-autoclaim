# AutoClaim - Lot 3 : Agent Google ADK + preuves BigQuery

## Fonctionnement

- `autoclaim_agent/agent.py` definit `root_agent`, sans habilitation : **aucune donnee accessible depuis `adk web` par defaut**.
- `create_agent(principal, retriever)` cree les outils pour une execution ADK donnee. Le principal est capture par les fonctions Python : le modele ne peut ni passer ni choisir de role.
- `prepare_coverage_review(claim_id)` appelle le moteur deterministe, puis **verifie en BigQuery** la presence exacte des references de CG utilisees. Une preuve absente bloque toute conclusion positive et tout montant.
- `search_contract_clauses(claim_id, query)` recherche dans BigQuery (lexical SEARCH) apres validation de l'acces au dossier, filtre de dates et de groupes, avec citations versionnees.
- Les CP et avenants sont encore dans les fichiers locaux representant un SI fictif. Seules les clauses CG sont chargees dans BigQuery.

## Verification locale sans appel cloud

```powershell
uv run python -m pytest -q
```

Le test de l'agent emploie le package ADK deja installe ; l'appel Gemini est simule / absent.

## Tester le parcours reel BigQuery sans appeler Gemini

```powershell
$env:AUTOCLAIM_GCP_PROJECT = "demo-gcp-project"
uv run python -m scripts.demo_adk --backend bigquery --simulate-group gestionnaires_auto --claim SIN-1001
```

Resultat attendu : `COVERED_IN_PRINCIPLE`, `indicative_amount_eur: 520`, preuves `BG-01` et `CALC-01` provenant de BigQuery. Les requetes BigQuery peuvent etre facturees.

Test ACL (groupe SIMULE) :

```powershell
uv run python -m scripts.demo_adk --backend bigquery --simulate-group gestionnaires_auto --claim SIN-1004
```

Attendu : `NOT_ACCESSIBLE`. Le code ne doit envoyer aucune requete BigQuery pour le dossier interdit. Le groupe superviseur permet quant a lui une preanalyse `DECHANCE_REVIEW` :

```powershell
uv run python -m scripts.demo_adk --backend bigquery --simulate-group superviseurs_auto --claim SIN-1004
```

## Premier appel Gemini + ADK (facturable)

Verifier la configuration Vertex AI dans la console PowerShell :

```powershell
$env:GOOGLE_GENAI_USE_ENTERPRISE = "TRUE"
$env:GOOGLE_CLOUD_PROJECT = "demo-gcp-project"
$env:GOOGLE_CLOUD_LOCATION = "eu"
$env:AUTOCLAIM_GCP_PROJECT = "demo-gcp-project"
uv run python -m scripts.demo_adk --backend bigquery --simulate-group gestionnaires_auto --claim SIN-1001 --execute
```

Le script appelle d'abord les outils, puis l'agent via `Runner` avec une session en memoire. Il ne remplace PAS un backend de production et ne fait aucune authentification de l'utilisateur final.

## Limites importantes avant toute exposition web

1. `--simulate-group` est **non securise** : CLI locale uniquement, jamais exposee via API ou Cloud Run.
2. `VerifiedPrincipal` est un conteneur, pas un verificateur de token. Dans le prochain lot, verifier un jeton d'identite/IAP sur le backend, puis resoudre les groupes Cloud Identity avec un compte technique minimal.
3. **Aucun code de ce lot ne prouve un test multi-comptes** ; cela sera valide avec IAP/Cloud Identity apres deploiement.
4. La CLI `--execute` effectue de vrais appels Gemini, potentiellement facturables. Meme sans `--execute`, les appels BigQuery sont reels en mode `--backend bigquery`.
5. `adk web` n'est pas un moyen de verifier les ACL : le `root_agent` y est anonyme et doit refuser l'acces. Utiliser le runner integre a un backend de confiance pour la suite.
6. Ce MVP est une **preanalyse** : il ne prononce aucun refus ni paiement. Les textes contractuels sont fictifs.
7. BigQuery est actuellement utilise comme retriever lexical, pas comme moteur de recherche semantique/vectorielle.
8. La future architecture multi-instance utilisera un service de sessions persistant et une identite de service GCP dediee ; `InMemorySessionService` ne couvre que le developpement.

## Suite - Lot 4

Construire une API HTTP securisee (Cloud Run + IAP), verifier l'identite cote backend et associer les groupes Cloud Identity aux deux comptes tests, sans exposer de parametre `simulate-group`.
