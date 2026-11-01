# Enterprise AI Agent AutoClaim

**Secure, evidence-backed AI copilot for motor insurance claim coverage pre-assessment**

Portfolio MVP built with **Google ADK + Gemini (Vertex AI), BigQuery, FastAPI, Cloud Run, and Google IAP**. It analyzes **entirely fictional** French motor-insurance claim scenarios, identifies relevant clauses, applies deterministic deductible/limit logic, and preserves a mandatory human decision.

> **Experimental demonstration only.** No real customer data. This application does **not** make binding coverage decisions, reject claims, determine legal forfeiture, or authorize payments.

## Demonstrated capabilities

- **Agent orchestration:** Google ADK tools bound to a backend-verified principal; the LLM cannot choose its own access groups.
- **Contract evidence retrieval:** BigQuery lexical `SEARCH` and exact citation lookup, with validity-date and document access filters.
- **Business logic:** deterministic pre-assessment of guarantee subscriptions, deductibles, ceilings, amendments, exclusions/possible forfeiture, with human review.
- **Provenance:** distinguish general conditions retrieved from BigQuery from structured policy/endorsement data in a fictional information system. Original signed documents are **not** verified.
- **Authentication:** Cloud Run + IAP; verify IAP JWT signature, audience and timestamps in FastAPI; deny by default.
- **Authorization:** app-level manager/supervisor access and claim-level authorization checks enforced before retrieval/LLM calls.
- **Operational telemetry:** Cloud Run native metrics plus sanitized structured events for HTTP activity, pre-assessment outcomes, and LLM calls.
- **Quality gates:** offline Pytest suite and GitHub Actions, with no API credentials required for tests.

## Sample result (fictional)

`SIN-1001`: *bris de glace*; coverage in principle, subject to human validation. Deductible **EUR 80**, ceiling **EUR 1,200**, indicative amount **EUR 520**. The response provides cited general conditions and policy values, identifying each source category. A manager is denied access to restricted `SIN-1004` (HTTP 404); a supervisor can inspect it subject to role configuration.

## Architecture

```text
Google users (Cloud Identity Free)
             |
          Cloud IAP  ---- access policy for the application
             |
          Cloud Run (private, FastAPI)
             |
       signed IAP JWT verification
             |
    application roles + dossier ACL
             |
       deterministic pre-analysis
          /                 \
  mock policy SI         BigQuery clauses
  (CP, endorsements)     (CG, version, dates, ACL)
          \                 /
         source-backed evidence
                   |
              Google ADK
                   |
          Gemini / Vertex AI
                   |
         advisory response only
                   |
       Cloud Logging & Monitoring
```

Security and data flows: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Deployment and operational checks: [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Project structure

```text
autoclaim_agent/    # ADK agent, coverage engine, repositories, retrieval, evidence
autoclaim_api/      # FastAPI/IAP authentication, authorization, web UI, telemetry
contracts/          # Fictional contract clauses (JSONL)
data/               # Fictional policies, endorsements, claims, expected outputs
scripts/            # BigQuery loading, retrieval, local ADK demo
tests/              # Unit / API / authorization / offline telemetry tests
docs/               # Architecture, runbook, implementation notes
.github/workflows/  # CI with Pytest
Dockerfile          # Cloud Run image using uv.lock
```

## Local setup

Requires Python 3.11, [uv](https://docs.astral.sh/uv/), and (only for live GCP calls) properly scoped Google Cloud credentials.

```powershell
uv sync --locked
uv run python -m pytest -q
```

Run the API locally for development only after configuring its required environment variables. There is deliberately **no bypass** for IAP identity verification. A browser-based local test without a valid IAP assertion will not grant business access.

Example dry run (uses only a simulated identity; **never publish as an API authentication mode**):

```powershell
uv run python -m scripts.demo_adk --backend bigquery --simulate-group gestionnaires_auto --claim SIN-1001
```

The live demo requires authorized GCP BigQuery access; `--execute` additionally invokes Gemini and may incur charges. The CLI is **not** a substitute for the IAP-protected deployed application.

## Evaluation and limitations

- Fictional corpus: **2 policies, 1 endorsement, 8 claim scenarios, 7 clauses**.
- Business rules and example amounts are fabricated for the demonstration; no legal or regulatory guarantee is inferred from them.
- RAG currently uses lexical search / exact citations, **not** semantic vector retrieval or OCR of signed PDFs.
- IAP authenticates real Google users. Business roles use an allowlist of **verified email addresses**, configured server-side; Cloud Identity group synchronization is not implemented.
- Sample contracts and claims are local JSON files. Replacing them with an audited private system of record is required before production use.
- Stateless HTTP deployment supports horizontal scaling, but **no load test, shared multi-turn session store, enterprise SLA or 400-user capacity test has been performed**.
- Operational telemetry intentionally excludes personally identifiable data, claim IDs, document contents, prompts and model responses. Token-cost tracking and distributed tracing are future work.

## Security and publication

Never commit `.env`, credentials, customer or claim information from actual operations, production documents, IAP JWTs, or real user emails. No real Cloud Identity account names should be hard-coded in this public repository. See the [runbook](docs/RUNBOOK.md) for scoped IAM assignments and deployment instructions.

## Suggested V2

Semantic/hybrid RAG, OCR and layout-aware parsing of signed contract documents, source-document reconciliation, enterprise identity group resolution, shared ADK sessions, human-review workflows, evaluation with a curated golden dataset, load testing and cost monitoring.
