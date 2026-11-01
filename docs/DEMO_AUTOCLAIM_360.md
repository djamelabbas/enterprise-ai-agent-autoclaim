# Demonstration client - AutoClaim 360 (5 minutes)

## Pitch (30 secondes)

"J'ai construit un agent Google ADK/Gemini integre a un portail de gestion
metier fictif. L'agent interroge un SI simule, retrouve les passages de
contrats et documents PDF/Word dans BigQuery, justifie sa reponse avec des
citations verifiables et respecte l'identite Google via IAP. Les decisions
sensibles restent reservees aux collaborateurs. Les controles sont couverts
par une suite de tests et les logs sont exploitables sur Cloud Run."

## Parcours

**00:30 - Cas d'usage**. Choisir `SIN-1001`, montrer la fiche contrat et les
pieces documentaires reellement consultables dans l'interface.

**01:15 - Agent grounded**. Ouvrir le widget, demander :
"Ce sinistre est-il couvert ? Cite les clauses et explique la franchise."
Montrer la preanalyse, les 80 EUR, les 1 200 EUR, la mention de validation
humaine et les sources effectivement confirmees.

**02:15 - RAG PDF/Word**. Poser : "Quels justificatifs doivent encore etre
verifies ?" Ouvrir la citation `DOC-GUIDE-BG-2026@v1.0#P001-01` ;
montrer la page du PDF source. Insister sur la separation entre clauses
contractuelles, notes de procedure et SI fictif.

**03:15 - Securite**. Dans la session gestionnaire, entrer `SIN-1004` et
constater le HTTP 404. La note interne de supervision n'est pas visible.
Basculer sur la session superviseur et montrer les droits distincts.

**04:15 - Gouvernance/MCO**. Montrer les tests GitHub Actions, les logs
Cloud Run, et decrire les controles de validation avant mise en production.

## Correspondance avec la mission Gemini Enterprise

- Agent Google ADK et Gemini : **oui**, demontre sur Cloud Run.
- Integration SI et documents : **oui en simulation**, via repository
  d'assurance fictif et ingestion de documents.
- IAM et controle d'acces : **oui**, IAP + role + dossier + document.
- Validation, observabilite, exploitation : **oui pour le MVP**.
- Administration Workspace, publication de l'agent dans Gemini Enterprise,
  400 utilisateurs simultanes : **non**, expliciter comme phases suivantes.

Ne jamais presenter cet outil fictif comme un service de production, une
application Google Gemini Enterprise configuree ou un outil d'indemnisation.
