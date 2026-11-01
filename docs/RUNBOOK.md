# Runbook — Exploitation AutoClaim MVP sur GCP

## 1. Environnement démonstration

- Projet : `demo-gcp-project`
- Région Cloud Run / BigQuery : `europe-west1`
- Localisation Vertex AI : `eu`
- Service : `autoclaim-coverage-mvp`
- Identité runtime : `autoclaim-mvp-sa@demo-gcp-project.iam.gserviceaccount.com`
- Dataset : `autoclaim_mvp` ; table `contract_clauses_demo`

Ces identifiants de ressources ne constituent pas des secrets ; les adresses des comptes utilisateurs, jetons et identifiants sensibles ne doivent **jamais** apparaître dans un dépôt public.

## 2. Vérification locale avant déploiement

```powershell
cd D:\PROJETS\enterprise-ai-agent-autoclaim
uv sync --locked
uv run python -m pytest -q
```

Attendu après installation du Lot 6 : **82 tests**, sans vrais appels GCP ou Gemini. La présence d'une dépréciation Starlette/httpx dans les tests est non bloquante ; éviter de modifier les versions de dépendances au milieu de la recette.

## 3. Vérification Cloud Run et IAP

```powershell
$PROJECT = "demo-gcp-project"
$SERVICE = "autoclaim-coverage-mvp"
$REGION = "europe-west1"

gcloud run services describe $SERVICE --project=$PROJECT --region=$REGION

gcloud run services get-iam-policy $SERVICE --project=$PROJECT --region=$REGION
```

Critères : `Iap Enabled: true`, bonne identité de service, et **aucun** `allUsers` / `allAuthenticatedUsers` avec `roles/run.invoker`. Le rôle `run.invoker` peut être attribué à l'identité IAP du projet, pas aux visiteurs finaux.

## 4. Permissions minimales de l'identité runtime

- Au projet : `roles/bigquery.jobUser` et `roles/aiplatform.user`, selon les APIs sollicitées.
- Au **dataset** `autoclaim_mvp` uniquement : `roles/bigquery.dataViewer`.
- La permission de build Cloud Storage est portée par l'identité de build et ne doit pas être confondue avec l'identité runtime.
- Pour le build Cloud Run source, vérifier le rôle `roles/run.builder` et, si les droits effectifs manquent sur le bucket source, ajouter la lecture `roles/storage.objectViewer` **au bucket concerné** à l'identité de build (et non à l'identité runtime).

## 5. Déploiement : préserver les paramètres existants

**Important :** avant toute relance, enregistrer la configuration (`gcloud run services describe`). `--set-env-vars` remplace certaines variables existantes : ne pas effacer involontairement les paramètres d'accès.

Après tests locaux, utiliser le déploiement déjà validé dans l'environnement :

```powershell
# PRE-REQUIS : service deja cree et variables d'environnement configurees.
gcloud beta run deploy autoclaim-coverage-mvp `
  --project=demo-gcp-project `
  --region=europe-west1 `
  --source=. `
  --service-account=autoclaim-mvp-sa@demo-gcp-project.iam.gserviceaccount.com `
  --iap `
  --no-allow-unauthenticated `
  --max-instances=2 `
  --concurrency=5 `
  --memory=1Gi `
  --timeout=120s
```

Contrôler `Iap Enabled: true` après la nouvelle révision. Ne pas désactiver IAP pour résoudre un problème OAuth/IAM.

## 6. Recette des deux comptes

| Test | Identité | Attendu |
|---|---|---|
| Page web et `/api/me` | Gestionnaire | HTTP 200 / `gestionnaires_auto` |
| `SIN-1001` — préanalyse | Gestionnaire | HTTP 200 / `COVERED_IN_PRINCIPLE`, 80 €, 1 200 €, 520 € |
| `SIN-1001` — preuve CP | Gestionnaire | `CP-POL-AUTO-001@v1.0#BRIS_GLACE` dans `contractual_evidence`, origine `SI_FICTIF` |
| `SIN-1004` | Gestionnaire | HTTP 404, aucun détail du dossier |
| `SIN-1004` | Superviseur | HTTP 200 / `DECHANCE_REVIEW` |
| `SIN-1001` — demander Gemini | Gestionnaire | Réponse documentée, avec validation humaine obligatoire |

Utiliser deux profils de navigateur séparés pour éviter de mélanger les sessions. Ne jamais coller un JWT IAP dans un ticket ou un dépôt.

## 7. Logs et monitoring

**Métriques Cloud Run natives** : console GCP → Cloud Run → service → *Metrics* (requêtes, latence, 4xx/5xx, CPU, mémoire, instances). Elles sont disponibles sans instrumentation supplémentaire.

**Logs récents** :

```powershell
gcloud run services logs read autoclaim-coverage-mvp `
    --project=demo-gcp-project `
    --region=europe-west1 `
    --limit=60
```

**Filtrer les événements structurés dans Logs Explorer** (https://console.cloud.google.com/logs/query?project=demo-gcp-project) :

```text
resource.type="cloud_run_revision"
resource.labels.service_name="autoclaim-coverage-mvp"
jsonPayload.event="coverage_review"
```

Remplacer la dernière ligne par `jsonPayload.event="http_request"` pour les codes HTTP, ou par `jsonPayload.event="llm_call"` pour les durées d'appels ADK/Gemini. Les traces contiennent uniquement une route normalisée et un statut : **jamais d'ID de sinistre, d'adresse utilisateur, de prompt ou de document**.

**Suivi minimum recommandé** : taux d'erreurs 5xx, p95 latence HTTP, `EVIDENCE_UNAVAILABLE` / `EVIDENCE_INCOMPLETE`, échecs `llm_call`, nombre d'instances et coût de la facturation. Les rejets HTTP 404 sont attendus dans les tests de sécurité : ne pas les assimiler à une panne.

Un seuil d'alerte de type « erreurs 5xx > 5 % » ne se justifie qu'après un volume suffisant de requêtes ; sur un MVP à faible trafic, privilégier une alerte sur **un nombre absolu d'erreurs** sur une fenêtre temporelle définie. Configurer la politique dans Monitoring après observation de la charge réelle.

## 8. Dépannage express

| Symptôme | Contrôle |
|---|---|
| 403 Cloud Run lors du build source | Vérifier les droits du SA de **build** sur le bucket `run-sources-*` |
| Connexion navigateur refusée | IAP actif ? Rôle `roles/iap.httpsResourceAccessor` attribué aux comptes concernés ? |
| HTTP 401 `/api/me` | Audience JWT IAP, signature et configuration `AUTOCLAIM_IAP_AUDIENCE` |
| HTTP 403 `/api/me` | Compte non présent dans les listes de rôles applicatives |
| HTTP 404 `SIN-1004` gestionnaire | Comportement attendu ; accès volontairement masqué |
| `EVIDENCE_UNAVAILABLE` | Lire le traceback serveur : `bigquery.tables.getData` et droits dataset `BigQuery Data Viewer` |
| Gemini indisponible | Rôle Vertex AI de l'identité runtime, quota, API, région et modèle |

## 9. Sécurité et limites

Le corpus est fictif. Aucune décision d'indemnisation ni accès à un système de production. Le projet ne démontre pas encore les ACL sur des documents signés, la synchronisation Cloud Identity, la haute disponibilité sous forte charge, la gouvernance de données réelles ni le coût complet d'inférence par dossier.
