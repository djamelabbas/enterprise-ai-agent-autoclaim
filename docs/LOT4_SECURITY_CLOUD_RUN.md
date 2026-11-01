# Lot 4 - API AutoClaim avec IAP, deux comptes et Cloud Run

## Ce que ce lot apporte

- API **FastAPI** en lecture seule (`/api/claims/{id}/review`, `/clauses`, `/ask`).
- Interface web minimale sur `/`, utilisable dans deux navigateurs/comptes Google.
- Authentification IAP avec validation **cryptographique** du JWT signe, audience, emetteur et dates.
- Autorisation applicative serveur : email issu du JWT verifie -> role metier ; jamais via un argument LLM.
- Filtrage par dossier et par clause avant restitution ou generation ; interdiction de consulter SIN-1004 avec le role gestionnaire.
- Appel Gemini ADK uniquement APRES verification de l'identite, du dossier et des preuves contractuelles.
- Code commente et tests offline. Un controle de groupes Cloud Identity live n'est **pas** implemente.

Le cas d'usage est fictif : le service ne prend pas de decision d'indemnisation.

## Limites de securite / architecture (a ne pas masquer)

1. **IAP + backend** : le perimetre Cloud Run doit rester prive (`--no-allow-unauthenticated --iap`). Les appels directs qui ne portent pas de JWT IAP valide sont refuses par l'application. Les headers non signes comme `X-Goog-Authenticated-User-Email` sont ignores.
2. **Roles MVP** : `AUTOCLAIM_MANAGER_EMAILS` et `AUTOCLAIM_SUPERVISOR_EMAILS` sont des listes blanches de comptes identifies par IAP. Elles ne prouvent PAS leur appartenance a un groupe Cloud Identity. Ce choix est volontaire : `checkTransitiveMembership` est reserve a certaines editions Enterprise / Cloud Identity Premium. Pour le scale, remplacer `resolve_groups()` par un service de permissions/annuaire privilegie avec cache et audit.
3. Le code ne possede aucun mode `DEMO_AUTH_BYPASS`. Les simulations `--simulate-group` du lot 3 restent **exclusivement CLI locales**.
4. Le SI sinistres et les CP/avenants sont stockes dans des JSON fictifs dans le conteneur. Les clauses CG sont dans BigQuery (recherche `SEARCH`, non vectorielle). Les conditions particulieres ne sont pas encore toutes disponibles comme extraits BigQuery ; ne pas pretendre le contraire.
5. Sessions ADK en memoire sur **une seule requete**. Pas de memoire conversationnelle entre requetes ; ajouter une session persistante au besoin en V2.
6. Les montants restent calcules de facon deterministe. Ni decisions juridiques, ni refus, ni ordres de paiement.
7. Garde-fous MVP : 2 instances max, 5 requetes concurrentes par instance, pas de vrai dossier client, IAM minimal et suppression de l'environnement apres demonstration.

## 1. Installation locale et tests (sans GCP)

Depuis `D:\PROJETS\enterprise-ai-agent-autoclaim` :

```powershell
Expand-Archive "$HOME\Downloads\autoclaim_lot4_secure_api.zip" -DestinationPath . -Force
uv add fastapi "uvicorn[standard]" google-auth
uv add --dev httpx
uv run python -m pytest -q
```

Les tests utilisent des identites/IAP simules UNIQUEMENT dans les tests, sans appels cloud. Aucun demarrage local sans token n'est possible via les routes `/api/` : c'est voulu.

## 2. Preparer le projet GCP et une identite d'execution limitee

```powershell
$PROJECT = "demo-gcp-project"
$REGION = "europe-west1"
$SERVICE = "autoclaim-coverage-mvp"
$PROJECT_NUMBER = (gcloud projects describe $PROJECT --format="value(projectNumber)").Trim()
$SA_NAME = "autoclaim-mvp-sa"
$SA = "$SA_NAME@$PROJECT.iam.gserviceaccount.com"

# Activer uniquement les API utiles (facturation GCP active requise).
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iap.googleapis.com aiplatform.googleapis.com bigquery.googleapis.com --project=$PROJECT

gcloud iam service-accounts create $SA_NAME --display-name="AutoClaim MVP Cloud Run" --project=$PROJECT

# Droits d'execution minimaux a l'echelle du projet pour les jobs et les modeles.
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/aiplatform.user"
```

**Dans BigQuery Console**, donner au compte `$SA` le role **BigQuery Data Viewer sur le dataset `demo-gcp-project.autoclaim_mvp` uniquement**, pas sur tous les datasets du projet. Ne jamais utiliser le compte service par defaut avec des droits d'edition larges.

Il peut etre necessaire d'accorder au deployeeur `roles/iam.serviceAccountUser` sur `$SA` et a l'identite Cloud Build les droits necessaires pour construire l'image. Ces roles dependent de la configuration de l'organisation.

## 3. Deploy Cloud Run + IAP (facturable)

Utiliser **deux comptes Google dont les emails sont connus**, de preference dans la meme organisation Cloud Identity. Le 1er sera gestionnaire ; le 2e superviseur.

```powershell
$MANAGER_EMAIL = "gestionnaire-test@votre-domaine.example"
$SUPERVISOR_EMAIL = "superviseur-test@votre-domaine.example"
$AUD = "/projects/$PROJECT_NUMBER/locations/$REGION/services/$SERVICE"

# Le conteneur utilise le Dockerfile present a la racine.
gcloud run deploy $SERVICE `
  --project=$PROJECT `
  --region=$REGION `
  --source . `
  --service-account=$SA `
  --iap `
  --no-allow-unauthenticated `
  --max-instances=2 `
  --concurrency=5 `
  --memory=1Gi `
  --timeout=120s `
  --set-env-vars "AUTOCLAIM_GCP_PROJECT=$PROJECT,AUTOCLAIM_BIGQUERY_LOCATION=$REGION,AUTOCLAIM_IAP_AUDIENCE=$AUD,AUTOCLAIM_MANAGER_EMAILS=$MANAGER_EMAIL,AUTOCLAIM_SUPERVISOR_EMAILS=$SUPERVISOR_EMAIL,GOOGLE_GENAI_USE_ENTERPRISE=TRUE,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=eu"
```

Sur certains tenants, l'activation initiale d'IAP et la configuration OAuth doivent etre faites dans **Cloud Run > service > Security > Require authentication > Identity-Aware Proxy (IAP)**. Un compte exterieur a l'organisation peut demander une configuration OAuth **External** et des droits admin additionnels. Ne pas desactiver IAP pour contourner un blocage.

```powershell
# IAP doit pouvoir invoquer le service Cloud Run prive.
gcloud services identity create --service=iap.googleapis.com --project=$PROJECT
$iapServiceAgent = "service-$PROJECT_NUMBER@gcp-sa-iap.iam.gserviceaccount.com"
gcloud run services add-iam-policy-binding $SERVICE --project=$PROJECT --region=$REGION `
  --member="serviceAccount:$iapServiceAgent" --role="roles/run.invoker"

# Autoriser les deux comptes a traverser IAP ; le role metier reste applique par l'API.
gcloud iap web add-iam-policy-binding --member="user:$MANAGER_EMAIL" --role="roles/iap.httpsResourceAccessor" --region=$REGION --resource-type=cloud-run --service=$SERVICE --project=$PROJECT
gcloud iap web add-iam-policy-binding --member="user:$SUPERVISOR_EMAIL" --role="roles/iap.httpsResourceAccessor" --region=$REGION --resource-type=cloud-run --service=$SERVICE --project=$PROJECT

# Obtenir l'URL HTTPS (connexion via navigateur Google authentifie).
gcloud run services describe $SERVICE --project=$PROJECT --region=$REGION --format="value(status.url)"
```

Un service prive reste protege par **IAP** et par la verification JWT de l'application. NE PAS donner `roles/run.invoker` aux comptes de test directement pour contourner IAP ; seul l'agent de service IAP doit invoquer cette application dans cette demonstration.

## 4. Recette multi-comptes (sur la vraie URL Cloud Run)

Ouvrir le service dans **deux profils de navigateur independants** (ou un profil et une fenetre de navigation privee). Confirmer `/api/me` pour chaque compte : les adresses et roles doivent etre differents.

| Test | Compte gestionnaire | Compte superviseur |
| --- | --- | --- |
| Se connecter a la page IAP | Autorise | Autorise |
| `/api/me` | `gestionnaires_auto` | `superviseurs_auto` |
| `SIN-1001` (bris de glace) | Couvert en principe ; 520 EUR indicatifs | Idem |
| `SIN-1004` (vol declare tardivement) | HTTP **404**, pas de contenu | `DECHANCE_REVIEW` avec revue humaine |
| Demander des roles dans le prompt | Aucune elevation de droits | Aucune elevation de droits |
| Bouton Gemini pour `SIN-1001` | Reponse documentee | Reponse documentee |

Verifier dans Cloud Logging que les erreurs techniques n'exposent ni tokens ni donnees sensibles. Les 2 comptes sont des identites reelles, mais les donnees restent fictives.

## 5. Diagnostic rapide

- **`403` Google avant l'app** : pas de permission IAP / utilisateur hors organisation / IAM IAP invoker. Verifier les politiques IAP et l'OAuth client, jamais `allUsers`.
- **`401` depuis l'API** : signature IAP non validee, audience incorrecte ou appel direct sans IAP. Verifier la variable `AUTOCLAIM_IAP_AUDIENCE` et l'en-tete signe sur Cloud Run.
- **`403` JSON de l'app** : compte authentifie par IAP, mais absent de la liste blanche metier.
- **`404` JSON de l'app** : dossier inexistant ou non autorise ; comportement volontaire anti-enumeration.
- **`503` JSON de l'app** : variables manquantes, BigQuery / Vertex AI indisponible ou preuves incompletes. Inspecter les logs techniques, sans desactiver les controles.
- **`SIN-1004` deja accessible au gestionnaire** : arreter la demonstration et revoir la resolution des roles avant toute suite.

## 6. Sources Google

- https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run
- https://docs.cloud.google.com/iap/docs/signed-headers-howto
- https://docs.cloud.google.com/identity/docs/how-to/query-memberships
- https://googleapis.github.io/google-api-python-client/docs/dyn/cloudidentity_v1.groups.memberships.html
