# AutoClaim 360 — Check-list de clôture V3

**Démonstration fictive.** Ce dossier permet de figer le code, la documentation et la preuve d'évaluation. Il ne constitue pas une certification de production ni un audit de sécurité complet.

## 1. Préparer et vérifier le dépôt (PowerShell)

```powershell
cd D:\PROJETS\enterprise-ai-agent-autoclaim
uv run python -m pytest -q
uv run python -m scripts.evaluate_business_rules
```

L'ajout de huit tests ciblés amène la suite historique de 152 à **160 tests attendus**, sous réserve de vérifier dans ton environnement local. Les deux artefacts issus de ta validation OCR sont requis :

```powershell
Test-Path .\contracts\ingested_images.jsonl
Test-Path .\demo_documents\manifest_images.json
```

Si l'un manque, ne pas créer d'index artificiel : reprendre l'étape d'approbation manuelle documentée dans `docs/LOT9_11_DEPLOIEMENT.md`.

## 2. Nouvelle évaluation RAG, sur le corpus déjà chargé dans BigQuery

Le corpus BigQuery V3 compte **12 passages** ; aucune réindexation n'est nécessaire pour les nouvelles questions. Exécuter un nouveau benchmark (requêtes facturables) :

```powershell
$ProjectId = "YOUR_GCP_PROJECT_ID"  # Remplacer par votre projet de demo
New-Item -ItemType Directory -Force -Path results | Out-Null
uv run python -m scripts.evaluate_retrieval `
  --mode compare `
  --project $ProjectId `
  --out results\benchmark_v3_ocr_release.json
```

**Contrôle de passage :** vérifier `forbidden_citation_count=0` pour chaque moteur. Examiner les trois cas ajoutés dans `results\benchmark_v3_ocr_release.json` : `Q13` doit retrouver `DOC-CONSTAT-VISUEL-2026@v1.0#IMG-01` dans le top 5 **en hybride** ; `Q14` (hors période) et `Q15` (mauvaise garantie) ne doivent jamais renvoyer cette référence. Comparer MRR@5 et Hit@5 aux mesures précédentes sans exiger le même score, car les données d'évaluation ont changé.

Le mode `hybrid` est déjà en service ; si les résultats révèlent une régression bloquante, effectuer une bascule sûre en lexical :

```powershell
gcloud beta run services update autoclaim-coverage-mvp `
  --project=$ProjectId --region=europe-west1 `
  --update-env-vars=AUTOCLAIM_RETRIEVAL_MODE=lexical
```

## 3. Vérifier les accès réels sur Cloud Run

Avec **gestionnaire**, contrôler que `SIN-1001` permet d'ouvrir le PNG sous IAP (code 200, `Content-Type: image/png`) ; avec ce même compte, un appel à `SIN-1004` donne 404. Les documents réservés au superviseur doivent rester introuvables. Avec **superviseur**, `SIN-1004` est visible. Le refus HTTP 404 de l'API compte autant que le masquage dans le portail.

URL documentaire (à ouvrir dans la session IAP autorisée) :

`https://YOUR_CLOUD_RUN_SERVICE_URL/api/claims/SIN-1001/documents/DOC-CONSTAT-VISUEL-2026`

**Question de recette :** « Que dit le constat visuel, quel montant de réparation y est annoncé et est-ce un document signé ? Cite ta source. » Attendu : source `IMG-01`, 600 EUR **annoncés**, document fictif **non signé**, validation humaine.

## 4. Vérifier les protections de publication

```powershell
git status --short
git add -A
git diff --cached --check
# Vérifier que les artefacts approuvés (JSONL + manifest) sont bien suivis.
git ls-files --cached -- contracts/ingested_images.jsonl demo_documents/manifest_images.json
# Vérifier les fichiers de secrets usuels et les identifiants professionnels.
git ls-files --cached | Select-String '\.env$|\.pem$|\.key$|\.venv/'
# Entrer votre identifiant GCP, votre nom de societe ou votre domaine professionnel.
$OrgPattern = Read-Host 'Motif interne a rechercher'
git grep --cached -n -E $OrgPattern
# Recherche de motifs de secrets connus.
git grep --cached -n -E 'BEGIN .*PRIVATE KEY|AIza[[:alnum:]_-]{25,}'
```

Ne pas publier de jetons, d'emails d'utilisateurs, de résultats internes, de vraies données métier ni de documents non fictifs. Les mentions d'environnement GCP présentes dans les scripts de documentation de démonstration sont à remplacer par des placeholders **avant publication publique** si elles ne doivent pas être exposées. Vérifier les différences manuellement et idéalement lancer un scanner de secrets.

## 5. Publication et validation CI

```powershell
git commit -m "feat: finalize AutoClaim V3 hybrid RAG, REST SI and reviewed vision OCR"
git push origin main
```

Vérifier sur GitHub Actions les **160 tests** (n'exécutent ni GCP ni Gemini) et contrôler le commit en place. Ne pas confondre tests hors ligne et validation réelle sur Cloud Run.

## 6. Gel de version

Une fois benchmark, recette, secret-scan et CI validés : créer un tag explicite (facultatif, mais recommandé) :

```powershell
git tag -a v3.0.0-demo -m "AutoClaim 360 V3 enterprise demonstration"
git push origin v3.0.0-demo
```

Pas de nouveau déploiement Cloud Run pour cette seule extension de **tests et documentation**. Conserver en local `results\benchmark_v3_ocr_release.json` (exclu du dépôt) comme élément de preuve ; partager uniquement un résumé dépersonnalisé.

## 7. Limites à annoncer au client

Agent ADK Cloud Run, **pas** Gemini Enterprise natif. Cloud Identity Free et IAP, **pas** Google Workspace. Connexion REST fictive en contrôle de cohérence, pas SI transactionnel. Images fictives et OCR validé humainement, pas lecture automatique d'originaux certifiés. Les garanties et calculs sont simulés. Aucune évaluation de montée en charge à 400 utilisateurs, aucun SLA démontré, aucune décision juridique ou paiement autonome.
