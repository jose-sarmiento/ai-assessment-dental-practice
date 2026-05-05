# Dental Practice AI — Design Document

## Goal

The MVP delivers a multi-agent assistant for a dental practice platform that automates three workflows: **patient scheduling**, **insurance/treatment Q&A**, and **claim follow-ups**. Every answer must be grounded in retrieved data with citations — no hallucination.

---

## Retrieval Design

Two retrieval paths serve different data types:

### 1. Structured Data — Appointments & Claims (Lexical)

Appointments and claims are assumed to already exist in the practice's primary database. This prototype simulates that with flat PostgreSQL tables.

**Why not vector search here?**
These records are queried by specific fields — patient name, provider, date, status, claim ID. Exact-match and full-text search (tsvector) is the right tool. Vector search is for semantic similarity, not structured lookups.

Each table has a `tsvector` column populated via trigger, enabling `websearch_to_tsquery` across names, procedures, and notes. The `appointment_id` and `claim_id` serve as citations.

**Queries this approach handles accurately where vector would struggle:**

- *"Show appointments for Dr. Reyes in May"* — provider name exact match
- *"What is the status of claim CLM-2024-003?"* — ID lookup
- *"Who has composite fillings scheduled?"* — procedure code/description match
- *"Show all denied claims for Delta Dental PPO"* — payer name + status filter
- *"Morning appointments for Jane Smith next week"* — name + time range + date range

Vector search would return semantically similar but incorrect records for these — a patient named "James Smith" or a claim with a similar description could rank higher than the exact match. Structured SQL with tsvector returns the precise record or nothing.

> In production, if the primary DB doesn't support full-text search (e.g. MySQL), Elasticsearch is the right replacement — not a code change, an infra swap.

> **TODO:** Consider adding vector search on `procedure_desc` for semantic procedure matching (e.g. user says "cleaning", system finds "Adult Prophylaxis"). Currently the agent relies on lexical + SQL filters which covers most cases, but concept-based procedure lookup is a gap.

### 2. Unstructured Data — Knowledge Base (Hybrid Vector + Lexical)

Company documents (PDFs, policy guides, FAQs) are ingested into the `data_sources` table via a RAG pipeline:

- **Parse** — Docling (handles PDF layout, tables, headings)
- **Chunk** — Docling HybridChunker (structure-aware)
- **Embed** — OpenAI `text-embedding-3-small` (1536d, batched)
- **Store** — pgvector (vector) + tsvector (lexical)
- **Retrieve** — both signals run independently, results merged via Reciprocal Rank Fusion (RRF)

Unlike structured data where lexical alone is sufficient, unstructured documents benefit from both: vector handles semantic meaning ("infection prevention practices" matches "standard precautions"), while lexical handles exact regulation numbers, procedure codes, and proper nouns that embeddings may not rank well.

Each chunk carries `metadata`: `{chunk_number, total_chunks, total_pages, page}` so the agent can traverse documents across conversation turns.

### Ingestion Pipeline

A driver pattern routes each file to the correct destination — adding a new entity type requires one new driver file and one line in the router:

```
File in
  ├── appointments.csv  →  AppointmentsDriver  →  appointments table (structured SQL)
  ├── claims.csv        →  ClaimsDriver        →  claims table (structured SQL)
  └── staff/ or patient/ subdir
        └── *.pdf / *.txt  →  DataSourcesDriver  →  data_sources table (RAG)
```

The folder name (`staff/`, `patient/`) sets the `audience` field at ingest time — no manual tagging required when adding new documents.

### Document Traversal

For multi-turn document reading, each `data_sources` record stores a `document_id` in `doc_{uuid}` format shared across all chunks of the same file. The agent can:

- `search_knowledge` — find relevant chunks globally
- `search_in_document(document_id, query)` — search within a known document
- `read_document(document_id, page)` — fetch all chunks for a specific page

Tool calls and their results are persisted to the session in guaranteed order (BIGSERIAL primary key), so on follow-up turns the agent has the exact `document_id` in context without needing to re-search.

### Citations

Every successful answer ends with a `Sources:` line. Citations are attached to every tool result as a `_citation` field — the AI selects only the ones it used, so citations reflect what was actually retrieved, not everything the tool returned.

- Appointments: `APT-001 (appointments/clinic-a)`
- Claims: `CLM-2024-001 (claims/clinic-a)`
- Knowledge: `dental_board_regs.pdf (p2)`

---

## Architecture

### Agent Design

#### BaseAgent

`BaseAgent` provides a shared streaming tool-use loop built on the OpenAI Responses API. It supports multi-step reasoning — the model can call tools, process results, and continue reasoning before producing a final answer, up to 15 steps per turn.

The loop emits three SSE event types to the client — `thinking`, `status`, and `token` — giving users a live view of what the agent is doing: a spinner while the model reasons, a contextual message when a tool is invoked, and streamed text for the final answer.

Additional capabilities:
- Parallel tool calls within a single response, each tracked independently
- Token usage and cost tracked across all steps including intermediate tool-call steps
- Automatic retry on transient API errors — up to 3 attempts with a 3-second delay
- 120s stream read timeout to handle network interruptions gracefully

#### PlannerAgent

`PlannerAgent` (`gpt-5.5`, reasoning effort `low`) is the entry point for `/agent`. It orchestrates the two subagents as tools:

- `appointment_scheduler` → delegates to `SchedulerAgent`
- `billing_claims` → delegates to `ClaimsAgent`
- `knowledge_retriever` → delegates to `RetrieverAgent`
- `document_summarizer` → delegates to `SummarizerAgent` (requires user confirmation before running)

The planner selects the appropriate subagent, delegates a self-contained query, and synthesises a coherent final response. Each subagent runs with its own session history — continuity is maintained per domain across conversation turns. Subagent internals are never exposed to the user.

#### ClaimsAgent

`ClaimsAgent` (`gpt-4.1`) is a dedicated Billing & Claims specialist:

- **Tool**: `search_claims` — queries billing records by patient, payer, procedure, status, or date range. Results include `billed_amount`, `insurance_paid`, and `patient_owed` fields.
- Handles: outstanding balances, denied claim follow-ups, coverage status, pending claim lists
- Patient sessions are scoped to their own claims via server-side `patient_id` injection

#### SchedulerAgent

`SchedulerAgent` (`gpt-4.1`) handles appointment workflows:

- **Staff tools**: `search_appointments`, `get_available_slots`, `draft_appointment`, `confirm_appointment`
- **Patient tools**: `search_appointments` only — scoped to their own records, read-only
- `get_available_slots` computes free slots on a 15-minute grid with a 15-minute buffer between appointments, validated against hardcoded provider schedules
- `draft_appointment` proposes without persisting — requires explicit user confirmation via `<select>` UI
- `confirm_appointment` writes to DB with a generated `APT-XXXXXX` ID

#### RetrieverAgent

`RetrieverAgent` (`gpt-4.1`) handles data retrieval across structured and unstructured sources:

- `search_appointments` — structured SQL with filters (date range, provider, patient, procedure, status, time)
- `search_claims` — structured SQL with filters (date range, payer, patient, status, procedure)
- `search_knowledge` — hybrid RAG search across all knowledge base documents
- `search_in_document` — hybrid RAG scoped to a specific `document_id`
- `read_document` — fetch chunks by page or range for document traversal across conversation turns

Both subagents are session-aware: prompt includes clinic name, current date/time, user role, and patient identity. Patient sessions cannot call booking or cross-patient tools.

#### SummarizerAgent

`SummarizerAgent` (`gpt-4.1`) produces comprehensive summaries of full documents without loading the entire content into a single context window:

- **Tools**: `read_pages(page_from, page_to)` — reads a batch of pages at a time; `save_summary(text)` — appends a structured batch summary to an internal accumulator
- Reads documents in batches of 4 pages, saving a structured summary per batch
- Uses a sliding window of the last 2 tool call pairs in `input_messages` — old page content is discarded as batches progress
- Current accumulated summary is injected into the system prompt on every step, giving the model context of what has already been summarised
- Produces a final compiled summary after all pages are processed
- The planner requires explicit user confirmation of the target document (by title, not `document_id`) before delegating to this agent

### Session History

Each agent maintains its own message history per session, stored in the `messages` table under an `agent` column:

| `session_id` | `agent` | content |
|---|---|---|
| `abc123` | `PlannerAgent` | user → fc:appointment_scheduler → fr:result → assistant |
| `abc123` | `SchedulerAgent` | user → fc:get_available_slots → fr:result → assistant |
| `abc123` | `RetrieverAgent` | user → fc:search_knowledge → fr:result → assistant |

Each agent resumes from its own history on every turn, providing full multi-turn context within its domain. Histories are fully isolated — scheduling context does not bleed into retrieval and vice versa.

### SSE Event Types

All endpoints stream Server-Sent Events:

| Type | When | Client behaviour |
|---|---|---|
| `thinking` | Start of each new loop step after the first | Show spinner |
| `token` | Response text deltas | Stream answer |
| `error` | Stream exception | Show error message |

Only `token` events form the saved answer. `thinking` is a transient UI signal.

### API

**`POST /session`** — creates a session storing tenant, role, and patient context. Returns `session_id`.

**`POST /agent`** — accepts `query` + `session_id`. Runs `PlannerAgent` → orchestrates subagents. Streams SSE events.

**`POST /ask`** — accepts `query` + `session_id`. Runs `RetrieverAgent` directly (no planner). Streams SSE events.

### Demo CLI

The prototype ships with two terminal clients (`ask.py`, `agent.py`) that exercise the full feature set — multi-tenancy, RBAC, streaming, session history, security tests, and the booking confirmation flow with `<select>` inputs.

> The CLI intentionally packs a lot into a terminal interface. Features like real-time streaming indicators, inline slot selection, and structured table output are deliberately compact given the medium — a web or mobile UI would surface these more naturally.

### Model Choices

| Component | Model | Notes |
|---|---|---|
| Planner | `gpt-5.5` | Orchestration, reasoning effort `low` |
| Subagents | `gpt-4.1` | Tool use, long context, streaming via Responses API |
| Embeddings | `text-embedding-3-small` | Cost-efficient, 1536 dimensions |

---

## Multi-Tenancy & Security

No built-in authentication for the prototype. Two tenants — **clinic-a** (Smile Dental Clinic) and **clinic-b** (Bright Smiles Dental) — are sufficient to demonstrate isolation.

Every database read filters by `tenant_id` at the SQL level — enforced in all tools and search queries. Cross-tenant data access is impossible regardless of query content.

Role-based access (staff vs patient) is enforced at three levels:
1. **Structured data** — patient sessions inject `patient_id` into every SQL tool call automatically
2. **Knowledge base** — `audience` field filters documents by role at query time
3. **Scheduler** — patient sessions receive a restricted tool list; booking tools are not exposed to patients

Knowledge base documents are scoped by role at ingest time using folder structure:

```
mock_data/
  clinic-a/
    appointments.csv     →  structured (all roles, patient_id injected for patients)
    claims.csv           →  structured (all roles, patient_id injected for patients)
    staff/               →  audience = "staff"
    patient/             →  audience = "patient"
  clinic-b/
    ...
```

### PHI Controls

Patient-identifying fields (`patient_name`, `patient_id`, `notes`) are redacted in all log output via a `PHIRedactFilter` applied globally to every log handler. Redaction operates at two levels:

1. **Field-level** — known sensitive keys masked before logging structured data
2. **String-level** — regex patterns catch serialized PHI in log messages

The agent's system prompt explicitly restricts patient sessions to their own records. Patient `patient_id` is injected server-side from the session — never from user input or the LLM.

### Safety/Compliance — Design Decision

A dedicated Safety/Compliance agent was considered but not built. The reasoning: by the time the LLM generates a response, the data it was given was already filtered at the SQL and vector layer — other patients' records never entered the tool results, staff-only documents never reached patient sessions, and cross-tenant data is physically unreachable. A post-generation LLM safety check would be evaluating a response already built from safe data, adding latency and cost for minimal security gain.

The stronger approach — and the one implemented — is enforcing safety at the data layer where it cannot be circumvented by model behaviour. A response-level safety agent would be the right next layer in production for detecting hallucinated PHI (names or IDs the model may have seen in training data), but it is not the primary control and is documented as a roadmap item.

---

## Observability

Every request logs at completion:

```json
{"ts": "...", "level": "INFO", "logger": "app.routers.agent", "msg": "[agent] done session=... latency=9.6s tokens=(3449in/217out) cost=$0.008634"}
```

- **Structured JSON logs** — every line is a parseable JSON object (`ts`, `level`, `logger`, `msg`)
- **Latency** — measured end-to-end per request
- **Token usage** — captured across all steps including tool-call steps; subagent usage is aggregated into the planner total per request
- **Cost estimate** — computed from token counts at model pricing
- **Rotating file** — `api/logs/api.log`, 10MB max, 5 backups
- **Debug mode** — set `DEBUG=true` in `.env` to enable verbose logging: loop steps, response text per step, full tool result payloads, subagent dispatch/return, final answer text

---

## LLMOps Plan

### Ingestion — Event-Driven Worker Architecture

The prototype ingests documents synchronously via `setup.py`. In production, ingestion moves to a job queue pattern on AWS:

```
Document uploaded to S3
        ↓
   API / Admin enqueues job
        ↓
   SQS Queue
        ↓
   Worker pool (ECS Fargate)
   polls queue, pops job, processes:
   ├── parse (Docling)
   ├── chunk (HybridChunker)
   ├── embed (OpenAI text-embedding-3-small)
   └── store (RDS pgvector)
```

Workers are long-running ECS tasks that continuously poll SQS and pop one job at a time. Each worker processes one document end-to-end — parse, chunk, embed, store — then deletes the message from the queue. If processing fails, the message becomes visible again after the visibility timeout and another worker picks it up. Failed messages after max retries move to a dead-letter queue for inspection.

The API is fully decoupled from ingestion. A document upload enqueues a job and returns immediately — the user never waits for embeddings to complete. Throughput scales horizontally by increasing the number of workers — more ECS tasks polling the same queue, no code changes required.

The deterministic `document_id` (derived from `tenant_id + filename`) ensures idempotent upserts — re-ingesting the same file is a no-op.

### Infrastructure as Code — Terraform

All AWS resources are defined in Terraform with shared modules and environment-specific variable files:

```
terraform/
  ├── modules/
  │   ├── networking/     # VPC, subnets, security groups
  │   ├── database/       # RDS PostgreSQL + pgvector extension
  │   ├── api/            # ECS Fargate cluster, task definition, ALB
  │   ├── ingest/         # S3 bucket, SQS, worker task definition
  │   └── observability/  # CloudWatch log groups, dashboards, alarms
  └── envs/
      ├── dev/            # minimal resources, single worker, no HA
      ├── staging/        # production-mirror, used for pre-release validation
      └── production/     # multi-AZ, autoscaling, enhanced monitoring
```

Each environment uses the same modules with different variable values — instance sizes, replica counts, worker counts, and retention policies differ per env. Staging mirrors production configuration so pre-release validation catches infra-level issues before they reach prod.

Tenant isolation is enforced at the infrastructure level — each tenant's documents land in a prefixed S3 path (`s3://bucket/{tenant_id}/`), and RDS row-level security mirrors the application-level `tenant_id` filter.

### CI/CD — GitHub Actions

```
On pull request:
  ├── lint + type check
  ├── unit tests (pytest)
  ├── eval harness — run gold sets, compare metrics against baseline
  └── block merge if hallucination rate or citation overlap degrades

On merge to main → deploy to dev:
  ├── build Docker image → push to ECR
  ├── terraform plan (dev)
  └── ECS rolling deploy → dev environment

On merge to main (scheduled or manual promote) → deploy to staging:
  ├── terraform plan (staging) — requires approval
  ├── ECS rolling deploy → staging
  └── smoke tests + eval harness against staging

On tag (release) → deploy to production:
  ├── terraform apply (production) — requires approval
  ├── ECS rolling deploy → production (zero-downtime)
  └── smoke tests against production endpoints
```

Staging acts as the final gate before production — it runs the same infrastructure and the same eval harness. A release only reaches production after staging passes.

### Model & Prompt Versioning

- Model IDs are pinned in config (`gpt-5.5`, `gpt-4.1`) — never resolved dynamically
- System prompts are versioned in source control — prompt changes go through PR review and trigger an eval run before merge
- If a model version is retired by OpenAI, a config change + CI run is all that's required to swap it

### Rollback Strategy

| Layer | Rollback mechanism |
|---|---|
| API | ECS previous task definition — one CLI command |
| Prompts | Git revert → CI redeploy |
| Model version | Config change → CI redeploy |
| DB schema | Flyway/Liquibase migration rollback |
| Ingestion | SQS dead-letter queue — failed messages replayed after fix |

### Monitoring & Alerting

CloudWatch dashboards track per-tenant metrics. Alarms fire on:
- p95 latency > 15s
- LLM error rate > 1%
- Token cost spike > 2× daily baseline
- Retrieval hit@k drops below threshold
- SQS queue depth growing (ingestion backlog)
