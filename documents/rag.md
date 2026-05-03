# RAG — Grounded Agent

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

---

## Multi-Tenancy

No built-in authentication for the prototype. Two tenants are hardcoded — **clinic-a** (Smile Dental Clinic) and **clinic-b** (Bright Smiles Dental) — which is sufficient to demonstrate tenant isolation.

Every database read — structured and vector — filters by `tenant_id` at the SQL level. Cross-tenant data access is impossible regardless of the query.

---

## Audience-Based Access Control

Knowledge base documents are scoped by role at ingest time using folder structure:

```
mock_data/
  clinic-a/
    appointments.csv          →  structured (all roles, filtered by patient_id for patients)
    claims.csv                →  structured (all roles, filtered by patient_id for patients)
    staff/                    →  audience = "staff"
      dental_board_regs.pdf
      insurance_faq.txt
    patient/                  →  audience = "patient"
      patient_welcome.pdf
  clinic-b/
    ...
```

The folder name sets `audience` in the DB at ingest. At query time, the session role filters:

- **Staff** — sees all documents
- **Patient** — sees only `audience IN ('all', 'patient')`

To test access control, select the role during the CLI onboarding. A patient asking about staff-only documents will receive no results.

---

## Citations

Every successful answer ends with a `Sources:` line. Citations are attached to every tool result as a `_citation` field — the AI selects which ones it actually used, so citations reflect what was retrieved, not everything the tool returned.

- Appointments: `APT-001 (appointments/clinic-a)`
- Claims: `CLM-2024-001 (claims/clinic-a)`
- Knowledge: `dental_board_regs.pdf (p2)`
