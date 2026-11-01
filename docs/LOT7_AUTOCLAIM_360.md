# Lot 7 - AutoClaim 360 : portail, chat et RAG PDF/DOCX

## Objectif

Faire evoluer le MVP AutoClaim en application metier fictive avec un copilote
conversationnel integre. Le projet reste une demonstration de competences
Google Cloud / ADK / Gemini, et non une instance de Gemini Enterprise.
Aucune decision d'indemnisation n'est automatisee.

## Fonctions livrees

- Portail responsive : liste des dossiers autorises, fiche sinistre, champs
  de contexte, vue documentaire et bouton de preanalyse deterministe.
- Chat flottant : ouverture depuis le portail, extension, questions suggerees,
  historique de suivi en memoire du navigateur, sources explicites.
- `POST /api/claims/{claim_id}/chat` : preanalyse verifiee, recherche documentaire,
  puis appel Google ADK / Gemini. Les sources retournees au navigateur proviennent
  du backend, pas de citations non verifiees generees par le modele.
- PDF et DOCX reels, entierement fictifs : un guide PDF (2 pages), une procedure
  Word pour gestionnaires et une note Word reservee aux superviseurs.
- Ingestion offline : extraction du texte, decoupage, citations versionnees et
  generation JSONL compatible avec la table BigQuery existante.
- Lecture des fichiers sources sous IAP, controle ACL du dossier, ACL du document,
  type de garantie et date de validite.

## Architecture V2

```text
Navigateur (portail / widget chat)
    |  question + 6 tours max de contexte NON FIABLE
Cloud Run + IAP -> signature JWT verifiee -> role serveur
    |                                      |
    |                             Controle du dossier
    |                                      |
    +--------------------- FastAPI --------+
                             |
               preanalyse deterministe (SI demo)
                             |
          recherche BigQuery SEARCH (CG + PDF/DOCX)
                             |
                 Google ADK / Gemini Vertex AI
                             |
            reponse + extraits de sources autorises
                             |
                   Cloud Logging sans PII
```

Le chat est **stateless** cote serveur : son historique est stocke uniquement
pendant la session du navigateur puis soumis a nouveau, limite a six messages.
L'historique n'est **pas** une source d'autorisation ou une preuve. Il n'existe
pas encore de sessions ADK partagees entre instances Cloud Run.

## Installer (Windows PowerShell)

Depuis le repertoire racine `enterprise-ai-agent-autoclaim` :

```powershell
Expand-Archive "$HOME\Downloads\autoclaim_lot7_autoclaim360.zip" -DestinationPath . -Force
uv run python -m pytest -q
```

Le projet n'ajoute **aucune dependance runtime** a `pyproject.toml` :
`uv.lock` reste identique. `pypdf` est necessaire uniquement pour re-generer
l'index PDF lors de l'operation d'ingestion offline ; les PDF/DOCX et leur
index extrait sont deja fournis dans le lot.

Pour verifier une nouvelle extraction depuis les documents fournis :

```powershell
uv run --with pypdf python -m scripts.ingest_documents
uv run --with pypdf python -m scripts.ingest_documents --execute
```

Verifier **sans ecriture** le chargement BigQuery (base fictive uniquement) :

```powershell
$ProjectId = "YOUR_GCP_PROJECT_ID"
uv run python -m scripts.seed_bigquery --project $ProjectId --include-documents
```

**Attention :** la commande d'ecriture ci-dessous remplace integralement
`YOUR_GCP_PROJECT_ID.autoclaim_mvp.contract_clauses_demo` par les 7 clauses CG et
les 4 passages PDF/DOCX. Ne jamais la lancer sur une table metier partagee.

```powershell
$ProjectId = "YOUR_GCP_PROJECT_ID"
uv run python -m scripts.seed_bigquery --project $ProjectId --include-documents --execute
```

Puis redeployer le meme service, sans aucune suppression de ses acces IAP :

```powershell
$ServiceAccount = "autoclaim-mvp-sa@$ProjectId.iam.gserviceaccount.com"
gcloud beta run deploy autoclaim-coverage-mvp `
    --project=$ProjectId `
    --region=europe-west1 `
    --source=. `
    --service-account=$ServiceAccount `
    --iap `
    --no-allow-unauthenticated `
    --max-instances=2 `
    --concurrency=5 `
    --memory=1Gi `
    --timeout=120s
```

Les identifiants de projet utilises dans ce guide sont des placeholders
compatibles avec la publication du depot public.

## Recette : cinq verifications

1. `manager@example.com` (placeholder pour le compte test IAP configure cote serveur) :
   ouvrir SIN-1001, consulter les 2 fichiers PDF/DOCX autorises.
2. `SIN-1001` : question "Quels justificatifs (facture, photos) ?" ; verifier
   les citations `DOC-GUIDE-BG-2026@v1.0#P001-01` et leur lien vers le PDF.
3. Poser "Et la franchise ?" : verifier la suite conversationnelle, les
   80 EUR issus des CP structurees, la validation humaine obligatoire.
4. Gestionnaire : tentative `SIN-1004` via la recherche ET l'API chat : HTTP 404.
   La note confidentielle `DOC-CONTROLE-SENSIBLE-2026` est invisible.
5. Superviseur : SIN-1004 accessible ; note sensible consultable ; la
   declaration tardive reste soumise a une revue humaine.

## Limites explicites

- **Gemini Enterprise** : l'agent ADK est heberge sur Cloud Run ; ce n'est
  pas un agent enregistre ni publie dans une application Gemini Enterprise.
- **Workspace** : les roles metier utilisent une allowlist serveur des emails
  IAP verifies ; synchronisation des groupes Google Workspace non implementee.
- **RAG** : recherche lexicale BigQuery `SEARCH` sans vecteurs, reranking
  semantique, OCR ou analyse multimodale des images. PDF texte et DOCX uniquement.
- **Sessions** : contexte borne dans le navigateur, sans stockage persistant
  ni isolation cryptographique de l'historique fourni par le client. Le
  backend reclasse les sources fiables et refait les controles ACL chaque tour.
- **Sources** : la couverture CP provient d'enregistrements structurels
  fictifs ; aucun original signe n'est verifie.
- **Production** : pas de scan de fichiers uploads, pas de connecteur REST
  reel au SI, pas de test de charge 400 utilisateurs, pas de SLA ni de
  validation de securite exhaustive.

## Observabilite

Les nouveaux endpoints HTTP et appels Gemini sont journalises sans identite,
contenu de question, documents, ID de sinistre ou reponse LLM.
Consulter `docs/RUNBOOK.md` pour l'exploitation de Cloud Logging.
