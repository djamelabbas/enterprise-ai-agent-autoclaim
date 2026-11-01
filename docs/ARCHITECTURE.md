# AutoClaim — Dossier d'architecture (MVP)

## 1. Objectif et périmètre

Préanalyser des sinistres auto sur un référentiel **fictif**, sans produire de décision de couverture juridiquement opposable, de refus ou de paiement. L'agent permet de consulter un dossier, de justifier la préanalyse à l'aide de références contractuelles, et de signaler les cas nécessitant une revue humaine.

**Composants :** Google Cloud Run (`autoclaim-coverage-mvp`, `europe-west1`), IAP, FastAPI, Google ADK, Vertex AI/Gemini (`eu`), BigQuery (`demo-gcp-project.autoclaim_mvp.contract_clauses_demo`), données SI simulées JSON.

## 2. Flux de sécurité et de données

1. L'utilisateur se connecte avec son compte Google via **IAP**. Aucun accès public direct au service n'est volontairement accordé.
2. L'API vérifie cryptographiquement le JWT `X-Goog-IAP-JWT-Assertion` : signature, émetteur, audience attendue, dates et sujet.
3. Le backend dérive le rôle applicatif de l'**adresse vérifiée par IAP**, selon une liste blanche configurée hors dépôt (`AUTOCLAIM_MANAGER_EMAILS`, `AUTOCLAIM_SUPERVISOR_EMAILS`). Ce mécanisme **n'interroge pas** les groupes Cloud Identity.
4. L'accès au dossier est contrôlé **avant** de déclencher une recherche documentaire ou un appel Gemini. Un dossier inconnu et un dossier interdit renvoient tous deux un HTTP 404, sans révéler l'existence du dossier.
5. Le moteur métier lit les données fictives du SI, vérifie garantie, dates, avenants et éventuels signaux d'exclusion/déchéance. Il calcule les montants par une règle **déterministe**, jamais par un calcul génératif.
6. Le retriever BigQuery récupère les clauses de CG par citation et/ou recherche textuelle, en filtrant dans le SQL les groupes autorisés et la date du sinistre.
7. Les CP et avenants sont reconstruits depuis des **enregistrements structurés du SI fictif**, étiquetés `SI_FICTIF` : ils ne sont pas présentés comme la lecture d'un document original signé.
8. Si une preuve requise manque, l'API renvoie `EVIDENCE_UNAVAILABLE` ou `EVIDENCE_INCOMPLETE` et bloque la conclusion positive. Si le dossier est interdit, aucun appel LLM n'est déclenché.
9. L'agent Google ADK reçoit des outils liés au principal vérifié. Il ne peut pas modifier ses groupes, et la réponse conserve le caractère **indicatif** et l'obligation de validation humaine.

## 3. Séparation des responsabilités

| Composant | Responsabilité | Limite |
|---|---|---|
| IAP | Authentification / accès à l'application | Pas les droits métier sur chaque sinistre |
| FastAPI | JWT IAP, rôles, contrôle d'accès au dossier | Rôles en allowlist, pas de synchronisation annuaire |
| Moteur `coverage.py` | Règles de garantie et calculs | Règles fictives non utilisables sur de vrais sinistres |
| BigQuery retriever | Recherche CG, ACL documentaires et datation | Recherche lexicale MVP et petit corpus |
| `structured_evidence.py` | Justification CP / avenants issus du SI fictif | Ne lit pas les CP originales signées |
| Google ADK / Gemini | Orchestration et synthèse argumentée | Pas de décision finale, pas de contournement IAM |
| Cloud Logging | Journaux opérationnels sans données sensibles | Pas de tracing distribué complet / coûts tokens |

## 4. Déploiement et scalabilité

Le service FastAPI est **stateless** côté HTTP et déployé avec une identité de service GCP dédiée. Cloud Run peut faire évoluer le nombre d'instances sous une limite configurée. `max-instances=2`, `concurrency=5` sont des paramètres **de démonstration**, pas des résultats de dimensionnement.

**Limitations actuelles :** sessions ADK en mémoire recréées à chaque requête (mono-tour), SI en fichiers locaux, pas de tests de charge, pas de stockage transactionnel, pas d'analyse de coût par réponse. V2 : sessions persistantes, base de données métier sécurisée, monitoring des tokens et corrélation des traces, isolation multi-tenant et simulations de charge.

## 5. Matrice minimale d'accès

| Profil | `SIN-1001` | `SIN-1004` | Accès direct aux rôles GCP |
|---|---|---|---|
| Gestionnaire | Oui | Non (HTTP 404) | Aucun requis |
| Superviseur | Oui | Oui (révision humaine) | Aucun requis |
| Non habilité IAP / application | Non | Non | Aucun |

À confirmer après chaque déploiement par des tests sur deux sessions Google indépendantes. Ne pas affecter de rôles GCP privilégiés aux comptes utilisateurs finaux.

## 6. Limites juridiques et données

Toutes les clauses, sinistres, polices et montants sont **fictifs**. Une exclusion ou une déchéance n'est jamais prononcée automatiquement. La confirmation d'une couverture ou d'un refus nécessite la lecture des documents originaux applicables et une intervention humaine compétente.
