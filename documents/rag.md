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

A `BaseAgent` provides a shared streaming tool-use loop built on the OpenAI Responses API:
1. Stream response from `gpt-4.1`
2. On `function_call` event → execute tool → append result → continue loop (supports parallel tool calls)
3. On `completed` with no tool calls → stream text response and exit

Max 15 steps per turn. Tool messages (calls + results) are persisted to the session alongside user/assistant turns, giving the agent full context on follow-up questions — including document IDs from previous searches.

`RetrieverAgent` extends `BaseAgent` with five tools:
- `search_appointments` — structured SQL with filters (date range, provider, patient, procedure, status, time)
- `search_claims` — structured SQL with filters (date range, payer, patient, status, procedure)
- `search_knowledge` — hybrid RAG search across all knowledge base documents
- `search_in_document` — hybrid RAG scoped to a specific `document_id`
- `read_document` — fetch chunks by page or range for document traversal across conversation turns

Prompt is session-aware: includes clinic name, user role, and patient identity. Agent may only answer from tool results and must cite sources on every response.

### API

**`POST /session`** — creates a session storing tenant, role, and patient context. Returns `session_id`.

**`POST /ask`** — accepts `query` + `session_id` with `X-Tenant-Id` and `X-User-Role` headers. Streams the response as Server-Sent Events (SSE). Only token events are sent to the client — tool calls and results are logged server-side.

### Fallback & Retry

The OpenAI client is configured with `max_retries=0` to fail fast. The agent loop handles retries itself — up to 3 attempts with a 3-second delay — so it can yield a "retrying" signal to the client rather than silently hanging. On exhausting retries the error surfaces immediately.

### Model Choices

| Component | Model | Notes |
|---|---|---|
| LLM | `gpt-4.1` | Strong tool use, long context, streaming via Responses API |
| Embeddings | `text-embedding-3-small` | Cost-efficient, 1536 dimensions |

---

## Multi-Tenancy & Security

No built-in authentication for the prototype. Two tenants — **clinic-a** (Smile Dental Clinic) and **clinic-b** (Bright Smiles Dental) — are sufficient to demonstrate isolation.

Every database read filters by `tenant_id` at the SQL level — enforced in all tools and search queries. Cross-tenant data access is impossible regardless of query content.

Role-based access (staff vs patient) is enforced at two levels:
1. **Structured data** — patient sessions inject `patient_id` into every SQL tool call automatically
2. **Knowledge base** — `audience` field filters documents by role at query time

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

---

## Observability

Every `/ask` request logs:

```json
{"ts": "...", "level": "INFO", "logger": "app.routers.ask", "msg": "[ask] done latency=3.1s tokens=(1403in/57out) cost=$0.003"}
```

- **Structured JSON logs** — every line is a parseable JSON object (`ts`, `level`, `logger`, `msg`)
- **Latency** — measured end-to-end per request
- **Token usage** — captured from OpenAI `response.completed` event
- **Cost estimate** — computed from token counts at gpt-4.1 pricing
- **Rotating file** — `api/logs/api.log`, 10MB max, 5 backups
