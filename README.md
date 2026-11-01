# Enterprise AI Agent AutoClaim

**Secure, evidence-backed AI copilot for motor insurance claim coverage pre-assessment**

Portfolio MVP built with **Google ADK + Gemini (Vertex AI), BigQuery, FastAPI, Cloud Run, and Google IAP**. It analyzes **entirely fictional** French motor-insurance claim scenarios, identifies relevant clauses, applies deterministic deductible/limit logic, and preserves a mandatory human decision.

> **Experimental demonstration only.** No real customer data. This application does **not** make binding coverage decisions, reject claims, determine legal forfeiture, or authorize payments.

## V2 - AutoClaim 360 Enterprise Chat

The demo now features a responsive fictional claims-management portal with a
ChatGPT-like assistant panel, bounded browser-held conversation context,
backend-authorized claim/document browsing, and actual **PDF/DOCX text
extraction** into BigQuery lexical RAG. Three fictional documents (one PDF and
two Word documents) are included, with document-level roles and versioned
citations. The agent still runs on **Google ADK/Vertex AI and Cloud Run**;
this is **not** an agent published in Google Gemini Enterprise.

See [`docs/LOT7_AUTOCLAIM_360.md`](docs/LOT7_AUTOCLAIM_360.md) for PowerShell
installation, document ingestion, BigQuery reseeding and deployment; see
[`docs/DEMO_AUTOCLAIM_360.md`](docs/DEMO_AUTOCLAIM_360.md) for the client demo.

## V3 - Hybrid retrieval, REST SI and vision/OCR

**Deployment status:** hybrid RAG and the read-only REST consistency check have been enabled and tested on the **demo Cloud Run environment**; a fictional PNG was indexed after a human OCR review. The code defaults to lexical retrieval in a fresh installation, and new users must configure their own deployment and identities.

- **P1 search quality:** Gemini Embedding 001 in `europe-west1`, separate BigQuery vector table, cosine-based semantic search, RRF lexical/semantic fusion, 15-question retrieval benchmark with Hit@5/MRR@5 and forbidden-citation checks (12 validated in the previous evaluation; 3 new OCR-focused cases require rerunning the GCP benchmark). Exact contractual evidence lookup is unchanged.
- **P2 integration:** a second, IAM-protected Cloud Run service implements a read-only fictional claims REST API. A Google ID-token connector compares its data to the dossier already authorized by FastAPI; no silent fallback.
- **P2 operations:** sanitized Cloud Logging events for retrieval mode, REST status, observed ADK tokens; a price-parameterized illustrative cost estimator, plus 8 business-rule golden cases.
- **P3 document vision:** a fictional PNG processed by an opt-in Gemini Vision/OCR pipeline, with human-approved transcription, versioned citations and image ACL. No image is indexed or displayed before operator approval.

Start with **[`docs/LOT9_11_DEPLOIEMENT.md`](docs/LOT9_11_DEPLOIEMENT.md)** (PowerShell, phased steps and rollback). Updated architecture: [`docs/ARCHITECTURE_V3.md`](docs/ARCHITECTURE_V3.md).

**Not included:** native Gemini Enterprise deployment, Google Workspace synchronization, automated legal decisions, production-grade semantic evaluation, real customer documents, OCR without review, a load test at 400 users.


## V3 — Enterprise architecture demo (November 2026)

This version extends the verified V2 with a **hybrid BigQuery RAG** (lexical `SEARCH` + Gemini embeddings at 768 dimensions + `COSINE_DISTANCE` + RRF), a separate read-only Cloud Run mock-SI REST service invoked through IAM, sanitized Gemini token telemetry, and Gemini Vision OCR of a **fictional image reviewed by a human before indexing**. The demonstration corpus contains 12 passages (7 clauses, 4 PDF/DOCX extracts, 1 approved PNG extraction).

A release-focused golden evaluation adds **three cases** to the prior 12: OCR retrieval (`Q13`), expired OCR (`Q14`), and OCR requested under the wrong coverage (`Q15`). Evaluate on GCP before treating these results as validated. The existing 12-case benchmark reported hybrid MRR@5=1.0 and no forbidden citations, on a tiny fictional corpus.

- [Architecture V3 with tradeoffs](docs/ARCHITECTURE_V3.md)
- [Release gates, benchmark and GitHub publication](docs/RELEASE_V3.md)
- [Client demonstration — Architecte IA / Gemini Enterprise](docs/DEMO_ARCHITECTE_IA.md)

The service uses **Google ADK on Cloud Run**, not a native Gemini Enterprise tenant. Google Workspace administration and group synchronization are not demonstrated, and 400-user capacity is not load-tested.

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

- Fictional corpus: **2 policies, 1 endorsement, 8 claim scenarios, 7 general-condition clauses + 4 extracted PDF/DOCX passages**.
- Business rules and example amounts are fabricated for the demonstration; no legal or regulatory guarantee is inferred from them.
- RAG uses lexical search / exact citations. It now extracts **text from demo PDF/DOCX** into chunks, but does **not** support OCR, images, embeddings, semantic search or parsing signed scanned documents.
- IAP authenticates real Google users. Business roles use an allowlist of **verified email addresses**, configured server-side; Cloud Identity group synchronization is not implemented.
- Sample contracts and claims are local JSON files. Replacing them with an audited private system of record is required before production use.
- The V2 supports bounded browser-supplied multi-turn history, which is treated as untrusted text and is never used for authorization. **No shared or persistent ADK session store, load test, enterprise SLA or 400-user capacity test has been performed**.
- Operational telemetry intentionally excludes personally identifiable data, claim IDs, document contents, prompts and model responses. Token-cost tracking and distributed tracing are future work.

## Security and publication

Never commit `.env`, credentials, customer or claim information from actual operations, production documents, IAP JWTs, or real user emails. No real Cloud Identity account names should be hard-coded in this public repository. See the [runbook](docs/RUNBOOK.md) for scoped IAM assignments and deployment instructions.

## Suggested next steps

Semantic/hybrid RAG, image/OCR and layout-aware parsing, source-document reconciliation, enterprise identity group resolution, managed ADK sessions, publishing in Gemini Enterprise where available, human-review workflows, golden-set evaluation, load testing and cost monitoring.
