# Lot 6 — Observabilité et clôture du MVP

## Ce que ce lot ajoute

- `autoclaim_api/observability.py` : événements JSON structurés `http_request`, `coverage_review`, `llm_call`, envoyés vers stdout pour Cloud Logging.
- `autoclaim_api/app.py` : middleware de latence HTTP ; événement métier après préanalyse autorisée ; événement appel ADK après succès/erreur.
- `tests/test_observability.py` : 7 nouveaux tests incluant la non-divulgation des IDs, emails, en-têtes et textes contractuels.
- `README.md`, `docs/ARCHITECTURE.md`, `docs/RUNBOOK.md` : dossier de démonstration et exploitation.
- `.github/workflows/tests.yml` : test suite sur les pushes / pull requests `main`.

Le service API continue de vérifier l'identité IAP et les ACL ; l'instrumentation n'ouvre aucun accès nouveau.

## Installation

```powershell
cd D:\PROJETS\enterprise-ai-agent-autoclaim
Expand-Archive "$HOME\Downloads\autoclaim_lot6_finalisation.zip" -DestinationPath . -Force
uv run python -m pytest -q
```

**Attendu : 82 passed**. Aucun appel Gemini ni GCP via cette suite.

## Déploiement (uniquement après tests)

Suivre le guide [`RUNBOOK.md`](RUNBOOK.md). Conserver `--iap`, `--no-allow-unauthenticated`, la même identité de service et les variables d'environnement existantes.

Après déploiement, déclencher un `SIN-1001` autorisé et un `SIN-1004` refusé, puis consulter Cloud Logging :

```text
resource.type="cloud_run_revision"
resource.labels.service_name="autoclaim-coverage-mvp"
jsonPayload.event="http_request"
```

Le log contient la route templatisée `/api/claims/{claim_id}/review`, jamais `/api/claims/SIN-1001/review`. Filtrez également `jsonPayload.event="coverage_review"` (statuts métier sans contenu), puis `jsonPayload.event="llm_call"` (succès/échec/durée).

## Publication GitHub : première fois

1. Vérifier `.gitignore` : `.env`, `**/.env`, `.venv/`, `results/`, `__pycache__/`, `.pytest_cache/`, `.adk/`, `.vscode/`.
2. Vérifier le contenu : **aucune clé, compte Google nominatif, donnée métier réelle**.
3. Ajouter les dossiers utiles et la CI, puis créer un commit.
4. Créer un dépôt GitHub sans README préinitialisé et pousser `main`.
5. Vérifier le workflow `Python Tests` sur GitHub Actions.

**Rappel :** le workflow valide uniquement les tests locaux et simulés ; il ne démontre pas à lui seul la disponibilité du service GCP ou la sécurité des comptes réels.

## V2 — Non inclus dans le MVP

Retrieval sémantique / hybride, évaluation RAG sur golden dataset, OCR de CP signées, annuaire Cloud Identity en direct, traces / coût tokens, workflows humains, tests de charge, bases métier externes et sessions ADK persistantes.
