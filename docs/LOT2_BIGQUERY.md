# AutoClaim — Lot 2 : retrieval contractuel BigQuery (MVP)

## Ce que cette etape valide

- 7 clauses fictives indexables dans BigQuery, avec dates de validite, groupe ACL, citation versionnee.
- Deux backends pour une meme interface : `LocalClauseRetriever` et `BigQueryClauseRetriever`.
- Recherche lexicale `SEARCH` (pas encore embedding/vector search) et classement par correspondance de termes.
- Filtre ACL **dans le SQL** en plus de la validation de la session avant appel.
- Requetes parametrees ; limitation des octets facturables ; pas de creation d'index sur 7 clauses.
- Tests locaux sans cout ni cles Google.

## Prerequis sur Windows PowerShell

Depuis `D:\PROJETS\enterprise-ai-agent-autoclaim` :

```powershell
uv add google-cloud-bigquery
uv run python -m pytest -q
```

Les nouveaux fichiers apportent **14 nouveaux tests** : total attendu **29 passed**.

## Configuration GCP de test

Utiliser un projet GCP **de test**, avec BigQuery API active, facturation,
`bigquery.jobs.create` et capacite a creer un dataset/charger une table.
L'identite ADC doit etre habilitee ; des roles larges ne sont pas requis en production.

```powershell
$env:AUTOCLAIM_GCP_PROJECT = "VOTRE_PROJET_GCP_DE_TEST"
$env:AUTOCLAIM_BQ_LOCATION = "europe-west1"
gcloud auth application-default login
gcloud services enable bigquery.googleapis.com --project=$env:AUTOCLAIM_GCP_PROJECT
```

La localisation BigQuery `europe-west1` est independante de la
multiregion Vertex AI `eu` utilisee pour Gemini.

## Ingestion protegee (ne remplace que la table dediee)

Premiere commande : **dry run**, aucune ecriture ni creation cloud.

```powershell
uv run python -m scripts.seed_bigquery --project $env:AUTOCLAIM_GCP_PROJECT --location $env:AUTOCLAIM_BQ_LOCATION
```

Puis pour charger les 7 lignes :

```powershell
uv run python -m scripts.seed_bigquery --project $env:AUTOCLAIM_GCP_PROJECT --location $env:AUTOCLAIM_BQ_LOCATION --execute
```

Destination fixe : `PROJET.autoclaim_mvp.contract_clauses_demo`.
`--execute` cree le dataset au besoin et **remplace uniquement** cette table de demonstration.
Ce chargement et les requetes BigQuery peuvent etre facturables.

## Rechercher les clauses

`--simulate-group` permet de tester le filtrage SQL, mais ne valide PAS
l'identite du compte GCP. **Ne jamais exposer cette CLI comme endpoint**.

```powershell
uv run python -m scripts.search_bigquery --project $env:AUTOCLAIM_GCP_PROJECT --query "bris de glace franchise" --event-date "2026-10-20" --coverage BRIS_GLACE --simulate-group gestionnaires_auto
```

Essai negatif (un gestionnaire ne doit pas recuperer `CONF-01`) :

```powershell
uv run python -m scripts.search_bigquery --project $env:AUTOCLAIM_GCP_PROJECT --query "note interne supervision" --event-date "2026-10-20" --simulate-group gestionnaires_auto
```

Essai positif (role superviseur simule, retrouve `CONF-01`) :

```powershell
uv run python -m scripts.search_bigquery --project $env:AUTOCLAIM_GCP_PROJECT --query "note interne supervision" --event-date "2026-10-20" --simulate-group superviseurs_auto
```

## Limites et prochains lots

1. **RAG lexical** : ni embeddings ni veritable recherche semantique. A ajouter plus tard sans changer l'interface.
2. **ACL applicative** : la securite de la requete repose sur `verified_groups`, fourni ici par la CLI de simulation. Le prochain lot apportera IAP + groupes verifies serveur pour tes deux comptes Google.
3. **Pas de RLS BigQuery native** pour ce MVP : compte technique BigQuery = service backend. Ne pas rendre ses identifiants accessibles aux utilisateurs.
4. **Pas de moteur de couverture connecte a BigQuery** a ce stade : `coverage.py` continue de valider les documents locaux. Prochain lot : agent ADK + outils avec identite injectee par le backend et citations.
5. **Recherche volumetrique** : le `SEARCH` fonctionne sans index pour les 7 clauses. Creer un search index / definir une strategie hybride plus tard, lorsque la volumetrie et les mesures le justifient.
6. Les donnees et règles sont **fictives** ; aucun refus d'indemnisation automatique.
