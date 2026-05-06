# Dental Practice AI — Principal AI Engineer Assessment

Multi-agent AI assistant for dental practice software automating patient scheduling, insurance/treatment Q&A, and claim follow-ups. Grounded answers with citations, multi-tenant, PHI-aware, RBAC-enforced.

## Documents

| Deliverable | Document |
|---|---|
| Design Document | [Google Doc](https://docs.google.com/document/d/1GAlRKQE15YfhsUKfBtsmnaD49TyUFtyFoS8alXCi8z0/edit?tab=t.dgwz1baxtk69) · [design-document.md](documents/design-document.md) |
| Readout | [Google Doc - Readout Demo](https://docs.google.com/document/d/1GAlRKQE15YfhsUKfBtsmnaD49TyUFtyFoS8alXCi8z0/edit?tab=t.s2odeybef1s5) |
| Demo Walkthrough | [demo.md](documents/demo.md) |

---

## Requirements

- Docker Desktop
- OpenAI API key

---

## Setup

**1. Configure environment**

```bash
cp .env.example .env
# Add OPENAI_API_KEY to .env
```

**2. Start services**

```bash
docker compose up --build
```

First build takes a few minutes. API available at `http://localhost:8000`.

**3. Verify**

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

If `"status": "degraded"` — proceed to step 4.

**4. Seed data**

```bash
docker compose exec api python setup.py
```

Creates the database, runs migrations, ingests mock appointments, claims, PDFs, and clinic FAQ for two tenants. Re-run health check to confirm ready.

---

## Run the Demos

See **[demo.md](documents/demo.md)** for the full walkthrough with scenarios and expected outcomes.

```bash
docker compose exec api python ask.py    # POST /ask  — RetrieverAgent direct
docker compose exec api python agent.py  # POST /agent — PlannerAgent + subagents
```

---

## Evaluation

```bash
docker compose exec api python eval/runner.py
```

Runs 15 gold set questions (appointments, claims, knowledge, security) through the live API. Each response is scored by an LLM evaluator. Outputs pass/fail per question with latency, citation check, and a summary.

![Eval Results](screenshots/eval%20result.png)

---

## API Reference

**Create session:**
```bash
curl -s -X POST http://localhost:8000/session \
  -H "X-Tenant-Id: clinic-a" \
  -H "X-User-Role: staff" \
  -H "Content-Type: application/json" \
  -d '{"tenant_name": "Smile Dental Clinic"}' | jq .
```

**`POST /ask` — grounded answer + citations:**
```bash
curl -s -X POST http://localhost:8000/ask \
  -H "X-Tenant-Id: clinic-a" \
  -H "X-User-Role: staff" \
  -H "Content-Type: application/json" \
  -d '{"query": "Show all pending claims", "session_id": "<session_id>"}' \
  --no-buffer
```

**`POST /agent` — multi-step tool use:**
```bash
curl -s -X POST http://localhost:8000/agent \
  -H "X-Tenant-Id: clinic-a" \
  -H "X-User-Role: staff" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is available for Dr. Reyes on May 7?", "session_id": "<session_id>"}' \
  --no-buffer
```

**Metrics:**
```bash
curl http://localhost:8000/metrics
```

---

## Tenants & Roles

| Tenant | ID | Role | Demo Patient |
|---|---|---|---|
| Smile Dental Clinic | `clinic-a` | `staff` / `patient` | Jane Smith (P-1001) |
| Bright Smiles Dental | `clinic-b` | `staff` / `patient` | Grace Gonzalez (P-1096) |

Pass `X-Tenant-Id` and `X-User-Role` headers on every request.

---

## Reset

```bash
docker compose exec api python setup.py --fresh
docker compose restart api
```
