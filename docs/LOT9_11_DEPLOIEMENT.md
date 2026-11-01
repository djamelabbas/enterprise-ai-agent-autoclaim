# Lots 9–11 — Déploiement progressif P1 / P2 / P3 (PowerShell)

**Objectif :** conserver la V2 stable, introduire la recherche sémantique mesurée, intégrer un faux SI REST externe, puis activer une ingestion image après revue humaine. Les données sont intégralement fictives. Les commandes avec `--execute`, `gcloud run deploy` et Gemini peuvent être facturées.

## 0 — Mettre à jour et vérifier

```powershell
cd D:\PROJETS\enterprise-ai-agent-autoclaim
Expand-Archive "$HOME\Downloads\autoclaim_lots9_11_entreprise.zip" -DestinationPath . -Force
uv run python -m pytest -q
uv run python -m scripts.evaluate_business_rules
```

**Attendu : 152 tests réussis** (126 existants + 26 supplémentaires), 8/8 règles métier. Un avertissement `StarletteDeprecationWarning` peut subsister sans bloquer les tests. L'application ne change pas de mode tant qu'aucune variable d'environnement n'a été modifiée.

## P1 — Embeddings + RAG hybride / benchmark

### 1. Préparer le corpus vectoriel

```powershell
$ProjectId = "YOUR_GCP_PROJECT_ID"
uv run python -m scripts.index_embeddings --project $ProjectId
```

**Attendu : 11 passages**, table cible `autoclaim_mvp.contract_embeddings_demo`, aucune écriture.

### 2. Indexer (action facturable)

```powershell
uv run python -m scripts.index_embeddings --project $ProjectId --execute
```

Le script utilise `gemini-embedding-001` à `europe-west1` pour les documents et stocke des vecteurs 768 dimensions dans une **nouvelle table** BigQuery. Il ne modifie pas la table documentaire actuelle.

### 3. Comparer objectivement les modes

```powershell
New-Item -ItemType Directory -Force -Path results | Out-Null
uv run python -m scripts.evaluate_retrieval --mode compare --project $ProjectId --out results\benchmark_v3.json
```

Examiner `hit_at_5`, `mrr_at_5`, `forbidden_citation_count` pour `lexical`, `semantic`, `hybrid`. **Condition minimale : aucune référence interdite, et mode hybride au moins aussi bon que le lexical sur les métriques de recherche retenues.** Avec 12 questions fictives seulement, il s'agit d'un signal exploratoire, non d'une validation statistique de production.

Ne pas se baser sur `--mode offline` pour la comparaison : cette version teste seulement les sept CG locales, sans les extraits PDF/DOCX de BigQuery.

### 4. Activer, uniquement si les résultats le justifient

```powershell
gcloud beta run services update autoclaim-coverage-mvp `
    --project=$ProjectId --region=europe-west1 `
    --update-env-vars=AUTOCLAIM_RETRIEVAL_MODE=hybrid
```

Tester `SIN-1001` avec ses justificatifs puis `SIN-1004` avec le gestionnaire. Pour revenir au lexical **sans déployer de code** :

```powershell
gcloud beta run services update autoclaim-coverage-mvp `
    --project=$ProjectId --region=europe-west1 `
    --update-env-vars=AUTOCLAIM_RETRIEVAL_MODE=lexical
```

## P2 — API REST métier séparée, sécurisée par IAM

La nouvelle API REST est autonome dans `si_mock_api/` et emploie des données **fictives copiées** depuis le dossier historique. Elle sert à démontrer une intégration via API. Le moteur de couverture continue d'utiliser les données locales et **compare** les valeurs REST avant de les exploiter : divergence ou indisponibilité = erreur explicite, aucun repli silencieux.

### 1. Créer l'identité du faux SI (une fois)

```powershell
gcloud iam service-accounts create autoclaim-si-demo-sa `
    --project=$ProjectId --display-name="AutoClaim SI Demo REST"
```

Ce compte n'a pas besoin de droits BigQuery ou Vertex AI.

### 2. Déployer l'API REST sans accès anonyme

```powershell
gcloud beta run deploy autoclaim-si-demo `
    --project=$ProjectId --region=europe-west1 `
    --source=si_mock_api `
    --service-account="autoclaim-si-demo-sa@$ProjectId.iam.gserviceaccount.com" `
    --ingress=all --no-allow-unauthenticated
```

**Choix réseau volontaire :** `--ingress=all` ne signifie pas public anonyme ; Cloud Run IAM bloque les invocations sans identité autorisée. `--ingress=internal` demande des paramètres VPC supplémentaires pour un appel Cloud Run → Cloud Run. Ne pas utiliser `--allow-unauthenticated`.

### 3. Autoriser uniquement le compte de service AutoClaim à invoquer le SI

```powershell
gcloud run services add-iam-policy-binding autoclaim-si-demo `
    --project=$ProjectId --region=europe-west1 `
    --member="serviceAccount:autoclaim-mvp-sa@$ProjectId.iam.gserviceaccount.com" `
    --role="roles/run.invoker"
```

### 4. Activer la vérification REST sur l'application métier

```powershell
$SiUrl = (gcloud run services describe autoclaim-si-demo `
    --project=$ProjectId --region=europe-west1 `
    --format="value(status.url)").Trim()

gcloud beta run services update autoclaim-coverage-mvp `
    --project=$ProjectId --region=europe-west1 `
    --update-env-vars="AUTOCLAIM_SI_MODE=rest,AUTOCLAIM_SI_URL=$SiUrl"
```

Avec le gestionnaire, ouvrir dans son navigateur IAP : `/api/claims/SIN-1001/si-check` → `status: MATCH`. Sur `SIN-1004`, le même utilisateur obtient HTTP 404. Lors de la conversation, les informations reçues du SI REST sont vérifiées contre les données déjà autorisées.

Rollback : `gcloud beta run services update autoclaim-coverage-mvp --project=$ProjectId --region=europe-west1 --update-env-vars=AUTOCLAIM_SI_MODE=local`.

## P2 — Monitoring, qualité et coûts

```powershell
# Régression de règles métier, sans appel Gemini
uv run python -m scripts.evaluate_business_rules

# Volume de tokens et métriques opératoires dans Cloud Logging
gcloud logging read `
  'resource.type="cloud_run_revision" AND resource.labels.service_name="autoclaim-coverage-mvp" AND jsonPayload.event="model_usage"' `
  --project=$ProjectId --limit=10 --format="table(timestamp,jsonPayload.model,jsonPayload.input_tokens,jsonPayload.output_tokens)"

# Recherche hybride ou fallback lexical
gcloud logging read `
  'resource.type="cloud_run_revision" AND resource.labels.service_name="autoclaim-coverage-mvp" AND jsonPayload.event="retrieval_search"' `
  --project=$ProjectId --limit=10 --format="table(timestamp,jsonPayload.mode,jsonPayload.result_count)"
```

L'estimation EUR demande **les prix actuels saisis par l'opérateur** :

```powershell
uv run python -m scripts.estimate_llm_cost `
  --input-tokens 100000 --output-tokens 20000 `
  --input-eur-per-million 0.50 --output-eur-per-million 2.00
```

Les deux tarifs ci-dessus sont **des valeurs purement illustratives, pas les prix officiels du modèle**. L'estimation ne vaut pas facture et ne couvre pas les coûts BigQuery, OCR, cache, embeddings ou infrastructure. Vérifier la facture dans Cloud Billing.

## P3 — Image et OCR multimodal avec approbation

Le fichier fictif `demo_documents/constat_visuel_demo.png` est fourni mais **ne devient visible dans la bibliothèque que si l'OCR a été effectué, relu et approuvé**.

### 1. Examiner l'image et lancer l'OCR (facturable)

```powershell
uv run python -m scripts.ingest_images
uv run python -m scripts.ingest_images --project $ProjectId --location eu --execute
```

Le résultat se trouve dans `results/image_ocr_pending.json` (ignoré par Git). **Lire et corriger manuellement cette extraction si nécessaire.** Le contenu OCR est une observation du modèle, non une preuve certifiée.

### 2. Approuver l'extraction relue

```powershell
uv run python -m scripts.ingest_images --approve
uv run python -m pytest -q
```

Cela crée : `contracts/ingested_images.jsonl` et `demo_documents/manifest_images.json`. Aucun appel GCP lors de l'approbation ; le SHA256 de l'image est vérifié.

### 3. Recharger le corpus fictif et ses embeddings

⚠️ **Destructif pour les seules tables de démonstration concernées** : la première commande remplace `autoclaim_mvp.contract_clauses_demo` par 7 CG + 4 extraits PDF/DOCX + 1 extrait OCR, soit 12 lignes. Ne jamais exécuter sur un dataset métier partagé.

```powershell
uv run python -m scripts.seed_bigquery --project $ProjectId --include-documents --include-images
uv run python -m scripts.seed_bigquery --project $ProjectId --include-documents --include-images --execute
uv run python -m scripts.index_embeddings --project $ProjectId --include-images --execute
```

### 4. Redéployer le portail pour servir le PNG sous IAP

```powershell
gcloud beta run deploy autoclaim-coverage-mvp `
    --project=$ProjectId --region=europe-west1 --source=. `
    --service-account="autoclaim-mvp-sa@$ProjectId.iam.gserviceaccount.com" `
    --iap --no-allow-unauthenticated `
    --max-instances=2 --concurrency=5 --memory=1Gi --timeout=120s
```

Vérifier sur `SIN-1001` la nouvelle source `DOC-CONSTAT-VISUEL-2026@v1.0#IMG-01`, l'accès au PNG et l'origine **document OCR non certifié**, sans jamais utiliser ce document seul pour conclure à une couverture.

## Recette de clôture

- Benchmark `lexical` versus `semantic` versus `hybrid` sauvegardé, **0 référence interdite** ; choix de mode documenté.
- `SIN-1001` correct, franchise 80 EUR et indemnisation indicative 520 EUR ; citations auditées.
- `SIN-1004` interdit au gestionnaire, accessible au superviseur.
- Note de supervision inaccessible au gestionnaire (bibliothèque, document direct, RAG).
- `/si-check` `MATCH` sur SIN-1001, refus pour dossier non autorisé, pas de fallback silencieux.
- OCR visible uniquement après revue, `source_system` distinct de la preuve documentaire originale.
- Tests offline et GitHub Actions verts, Logs `retrieval_search`, `si_connector`, `model_usage` consultables.
