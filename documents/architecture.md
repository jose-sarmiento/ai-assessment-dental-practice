# Architecture

## Overview

A multi-agent AI assistant for dental practice software that answers questions about appointments,
claims, and insurance policies using retrieval-augmented generation (RAG). The system is
multi-tenant and produces grounded answers with citations.

See [rag.md](rag.md) for the full retrieval design.

---

## Agent Design

### BaseAgent

Shared streaming tool-use loop built on the OpenAI Responses API:
1. Stream response from `gpt-4.1`
2. On `function_call` event → execute tool → append result → continue loop (supports parallel tool calls)
3. On `completed` with no tool calls → stream text response

Max 15 steps per turn. Tool messages (calls + results) are persisted to the session alongside user/assistant turns, giving the agent full context on follow-up questions including document IDs from previous searches.

### RetrieverAgent

Extends `BaseAgent`. Tools:
- `search_appointments` — structured SQL with filters (date range, provider, patient, procedure, status, time)
- `search_claims` — structured SQL with filters (date range, payer, patient, status, procedure)
- `search_knowledge` — hybrid RAG search on `data_sources` (global)
- `search_in_document` — hybrid RAG scoped to a specific `document_id`
- `read_document` — fetch chunks by page or range for document traversal across turns

Prompt is session-aware: includes clinic name, user role, and patient identity (for patient sessions). Agent may only answer from tool results and must cite sources on every response.

---

## API

### `POST /session`

Creates a session storing tenant, role, and patient context. Returns a `session_id` used for all subsequent requests.

### `POST /ask`

Accepts `query` + `session_id` with `X-Tenant-Id` and `X-User-Role` headers. Loads session context, runs RetrieverAgent, streams the response as **Server-Sent Events (SSE)**:

```
data: {"type": "tool_call", "name": "search_appointments", "args": {...}}
data: {"type": "tool_result", "count": 3, ...}
data: {"type": "token", "value": "Here are..."}
data: {"type": "citations", "value": [...]}
data: [DONE]
```

---

## Model Choices

| Component | Model | Notes |
|---|---|---|
| LLM | `gpt-4.1` | Strong tool use, long context, streaming via Responses API |
| Embeddings | `text-embedding-3-small` | Cost-efficient, 1536 dimensions |

> Model selection trade-offs (latency / cost / privacy) to be documented once baseline metrics are available.

---

## Multi-Tenancy & Security

Every database read filters by `tenant_id` at the SQL level — enforced in all tools and search queries. No cross-tenant data can be returned regardless of query content.

Role-based access (staff vs patient) is enforced at two levels:
1. **Structured data** — patient sessions inject `patient_id` into every SQL tool call automatically
2. **Knowledge base** — `audience` field filters documents by role at query time

No built-in authentication for the prototype. Two tenants (`clinic-a`, `clinic-b`) and two roles are sufficient to demonstrate isolation.
