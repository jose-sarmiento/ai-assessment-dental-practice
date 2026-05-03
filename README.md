# Dental Practice AI

A multi-agent AI assistant for dental practice software. Answers questions about appointments,
claims, and insurance policies using retrieval-augmented generation (RAG) with citations.

## Requirements

- Docker + Docker Compose
- OpenAI API key

## Setup

**1. Configure environment**

```bash
cp api/.env.example .env
```

Open `.env` and add your `OPENAI_API_KEY`.

**2. Start services**

```bash
docker compose up --build -d
```

This starts PostgreSQL (port 5433) and the API (port 8000).

**3. Run setup**

Runs migrations and seeds mock data automatically.

```bash
docker compose exec api python setup.py
```

## Try it

```bash
docker compose exec api python ask.py
```

You'll see a menu of prepared questions across Appointments and Claims. Enter a number to
select one or type your own question.

```
Appointments:
  1. Show me all appointments for Dr. Reyes in May 2026
  2. What are the morning appointments scheduled for next week?
  ...

Claims:
  6. Show all pending claims
  7. What claims has Jane Smith filed?
  ...

You (enter number or type question):
```

Type `exit` to quit.

## API

The REST API runs at `http://localhost:8000`.

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: clinic-demo" \
  -H "X-User-Role: staff" \
  -d '{"query": "Show appointments for Dr. Reyes in May"}'
```

Health check:

```bash
curl http://localhost:8000/health
```
