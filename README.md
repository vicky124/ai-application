# Enterprise Policy, Compliance & HR Operations Copilot

A grounded, auditable AI assistant that answers employee questions about company policy
(HR, IT, security, legal, compliance) with citations, and (planned) handles routine HR operations.
Built on open-source models: local embeddings via FastEmbed and LLMs served by Ollama.

| Concern | Implementation |
|---|---|
| RAG | LangChain + Qdrant, heading-aware chunking, status and role filters at query time |
| Hallucination prevention | Mandatory citations, rule-based verifier (citation validity, coverage, numbers present in sources), bounded retry, abstain |
| Multi-agent orchestration | LangGraph state graph (guard, retrieve, generate, verify, abstain); more agents planned |
| Guardrails | Prompt-injection check, RBAC on retrieval, permission-checked endpoints |
| Identity | PostgreSQL `auth` schema, JWT access + rotating refresh tokens, Argon2 passwords, lockout, access levels, audit log |
| Observability | Per-request step trace returned to the UI; Langfuse/Phoenix planned |

## Documentation
- [Implementation guide](docs/implementation.md): architecture, modules, agent flow, API and config reference, extension guides, testing, limitations
- [Requirements analysis](docs/requirements-analysis.md): scope, requirements, phases

## Status
**Phase 1 (foundation) done:** ingestion, RAG with citations, abstention, RBAC, model selection, React chat UI.
See [docs/requirements-analysis.md](docs/requirements-analysis.md) for the full roadmap.

## Authentication and authorization
Users, roles and sessions are stored in PostgreSQL (schema `auth`). Roles carry an access **level** and a set of
**permissions**; endpoints check permissions. Login returns a 15-minute JWT and a rotating refresh token; accounts lock
after repeated failures; every security event is audited. REST endpoints: `/auth/login|refresh|logout|logout-all|change-password`
and `/api/me|users|roles|audit-log` (interactive docs at http://localhost:8010/docs). Details in the
[implementation guide](docs/implementation.md#7a-identity-authentication-and-authorization).

## Ingestion pipeline with live steps
HR, compliance and admin users get an **Ingestion** tab. Upload a `.md`, `.txt` or `.pdf` file and watch seven stages
run: receive, parse, clean, chunk, embed, store in Qdrant, verify. Each stage shows its details (chunk previews,
embedding model and dimensions, a vector preview, collection and point IDs, and a self-retrieval check). The same
pipeline is available as a streaming API: `POST /api/documents/ingest`. See the
[implementation guide](docs/implementation.md#47-ingestion-pipeline-ragpipelinepy-ragingestpy-ragtextpy).

## Model selection
- **Config level:** `ModelSpec` list in [`backend/app/config.py`](backend/app/config.py), or a JSON file via `MODELS_CONFIG`
  (`[{"id","label","provider","name","default"}]`). Defaults: Llama 3.1 8B, Qwen 2.5 7B, Mistral 7B (Ollama) and an offline extractive mode.
  Embeddings are fixed per collection (vector size), so they are chosen in config only (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`).
- **Application level:** the UI has a model dropdown fed by `GET /api/models`; each chat request sends `model_id`.

## Design (SOLID)
- **Single responsibility:** parsing, chunking, storage, ingestion, generation, verification, guarding and orchestration are separate modules.
- **Open/closed:** new LLM providers, embedding providers and file parsers are added by registering a class (`Registry`, `ParserRegistry`), not by editing callers.
- **Liskov:** every `AnswerGenerator` (Ollama via LangChain, extractive) is interchangeable behind the same contract.
- **Interface segregation:** small Protocols in [`app/interfaces.py`](backend/app/interfaces.py) (`VectorStore`, `AnswerGenerator`, `Verifier`, `InputGuard`, `DocumentParser`).
- **Dependency inversion:** the agent and ingestion service depend on those Protocols; [`app/container.py`](backend/app/container.py) is the only composition root.

## Run locally
Prerequisites: Python 3.11+, Node 18+, **PostgreSQL 14+** (for users), and optionally [Ollama](https://ollama.com)
(`ollama pull llama3.1:8b`).

**1. Database.** Either `docker compose up -d postgres`, or on an existing server create a database and role
(run as a superuser):
```sql
CREATE ROLE policy LOGIN PASSWORD 'policy';
CREATE DATABASE policy_copilot OWNER policy;
```
Use a different URL via `DATABASE_URL` (see `backend/.env.example`). The schema and tables are created by migration at startup.
Prefer plain SQL? The [db/](db/README.md) folder has `schema.sql`, `sample_data.sql` and `drop_schema.sql` for the same schema.


**2. Backend and frontend**
```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m uvicorn app.api.main:app --port 8010
```

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. On first start with an empty users table, demo accounts are created (local development only,
`SEED_DEMO_USERS=false` disables it): `alice/alice123` (employee), `mark/mark123` (manager), `hannah/hannah123` (HR),
`carl/carl123` (compliance), `root/root123` (admin). Create a real administrator with
`python -m app.db.manage create-admin --username <name>`.
Without Ollama, pick "No LLM (extractive, offline)". The first start downloads the embedding model and indexes `backend/data/sample_docs`.

Optional services (Qdrant server, Ollama): `docker compose up -d`, then set `QDRANT_URL` (see `backend/.env.example`).

## Tests
```bash
cd backend
.venv/Scripts/python -m pytest        # 59 tests; uses SQLite unless TEST_DATABASE_URL points to Postgres
```

## Layout
```
backend/app/   api, agents (LangGraph), providers (LLMs), rag (chunk/embed/store/ingest), auth, container
frontend/      React + Vite chat UI
docs/          Requirements analysis
```
