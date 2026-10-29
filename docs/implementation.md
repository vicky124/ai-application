# Implementation Guide (Phase 1)

This document describes how the Policy & HR Copilot is built today: architecture, modules, request flow,
APIs, configuration, extension points, testing, and known limitations. For *what* the system must do, see
[requirements-analysis.md](requirements-analysis.md).

Contents
1. [Overview](#1-overview)
2. [Repository layout](#2-repository-layout)
3. [Architecture and design principles](#3-architecture-and-design-principles)
4. [Backend modules](#4-backend-modules)
5. [Request flow: the agent graph](#5-request-flow-the-agent-graph)
6. [Hallucination prevention](#6-hallucination-prevention)
7. [Guardrails and access control](#7-guardrails-and-access-control)
   - [7A. Identity: authentication and authorization](#7a-identity-authentication-and-authorization)
8. [Model selection](#8-model-selection)
9. [Data model and Qdrant storage](#9-data-model-and-qdrant-storage)
10. [HTTP API reference](#10-http-api-reference)
11. [Configuration reference](#11-configuration-reference)
12. [Frontend](#12-frontend)
13. [Extending the system](#13-extending-the-system)
14. [Testing](#14-testing)
15. [Running and operating](#15-running-and-operating)
16. [Known limitations and roadmap](#16-known-limitations-and-roadmap)
17. [Requirements traceability](#17-requirements-traceability)

---

## 1. Overview

A user signs in, asks a policy question, and receives an answer that cites approved company documents.
Behind the chat box a LangGraph workflow screens the question, retrieves role-permitted chunks from Qdrant,
asks the selected model for a cited answer, verifies the answer against the sources, and either returns it
or abstains.

Stack

| Layer | Technology |
|---|---|
| API | Python, FastAPI, Pydantic |
| Orchestration | LangGraph (`StateGraph`) |
| Retrieval | LangChain `langchain-qdrant`, Qdrant (embedded local mode or server) |
| Embeddings | FastEmbed, ONNX, `BAAI/bge-small-en-v1.5` (open source, local) |
| LLMs | Ollama via `langchain-ollama` (Llama 3.1, Qwen 2.5, Mistral) or an offline extractive mode |
| Frontend | React 18, Vite, Tailwind CSS 4 |
| Auth | JWT (PyJWT), demo users |

```mermaid
flowchart LR
  UI[React UI] -->|JWT + question + model_id| API[FastAPI]
  API --> AG[LangGraph PolicyAgent]
  AG --> G[InputGuard]
  AG --> VS[(Qdrant via QdrantPolicyStore)]
  AG --> GEN[AnswerGenerator\nOllama or Extractive]
  AG --> V[Verifier]
  ING[IngestionService] --> VS
```

## 2. Repository layout

```
ai-application/
├── backend/
│   ├── app/
│   │   ├── api/main.py          FastAPI app, routes, startup (sample ingestion)
│   │   ├── agents/
│   │   │   ├── graph.py         PolicyAgent: LangGraph workflow
│   │   │   ├── components.py    RegexInputGuard, CitationVerifier (rule checks)
│   │   │   ├── claims.py        Splits answers into cited claims
│   │   │   ├── evidence.py      Numbers, wording coverage, negation, clauses
│   │   │   ├── checkers.py      Offline and LLM claim checkers, fallback
│   │   │   └── verifier.py      ClaimVerifier, hints, confidence
│   │   ├── providers/
│   │   │   └── generators.py    AnswerGenerator impls, GENERATORS registry, ModelCatalog
│   │   ├── rag/
│   │   │   ├── chunking.py      Heading-aware chunker
│   │   │   ├── embeddings.py    Embeddings impls + EMBEDDINGS registry
│   │   │   ├── parsers.py       DocumentParser impls + ParserRegistry
│   │   │   ├── store.py         QdrantPolicyStore (VectorStore + VectorIndex impl)
│   │   │   ├── pipeline.py      IngestionPipeline: 7 observable stages emitting events
│   │   │   ├── ingest.py        IngestionService (blocking use, directory loading)
│   │   │   ├── text.py          Front-matter parsing, text cleaning
│   │   │   ├── rerank.py        Cross-encoder reranking (RerankingRetriever)
│   │   │   └── manage.py        reindex and ingest-samples CLI
│   │   ├── eval/                Retrieval golden-set evaluation and the verifier evaluation (verifier_eval.py)
│   │   ├── auth/                Passwords, JWT, repositories, services, deps, REST router
│   │   ├── db/                  SQLAlchemy models (schema `auth`), sessions, bootstrap, CLI
│   ├── alembic/                 Migration 0001 (auth schema)
│   │   ├── config.py            Settings, ModelSpec, default model list
│   │   ├── container.py         Composition root (dependency wiring)
│   │   ├── domain.py            Framework-free dataclasses
│   │   ├── interfaces.py        Protocols (contracts)
│   │   └── registry.py          Generic named-factory Registry
│   ├── data/sample_docs/        Markdown policies with front matter
│   ├── tests/                   pytest unit and API tests
│   ├── requirements.txt
│   └── .env.example
├── frontend/src/                App.jsx, api.js, components/{Login,Message}.jsx, styles.css
├── docs/                        This guide and the requirements analysis
└── docker-compose.yml           Qdrant server and Ollama (optional)
```

## 3. Architecture and design principles

The code follows SOLID. Each principle maps to concrete files:

| Principle | How it is applied |
|---|---|
| **S**ingle responsibility | One concern per module: parsing (`parsers.py`), chunking (`chunking.py`), storage (`store.py`), ingestion orchestration (`ingest.py`), generation (`generators.py`), verification and guarding (`components.py`), workflow (`graph.py`), HTTP (`api/main.py`). |
| **O**pen/closed | `Registry` (`registry.py`) and `ParserRegistry` let you add an LLM provider, embedding provider or file type by registering a class. No existing code changes. |
| **L**iskov substitution | `LangChainGenerator` and `ExtractiveGenerator` both satisfy `AnswerGenerator`; the agent cannot tell them apart. Both return either a cited answer or the sentinel `INSUFFICIENT_CONTEXT`. |
| **I**nterface segregation | `interfaces.py` has five narrow Protocols (`DocumentParser`, `VectorStore`, `AnswerGenerator`, `Verifier`, `InputGuard`). Consumers depend only on the methods they use. |
| **D**ependency inversion | `PolicyAgent` and `IngestionService` receive abstractions through their constructors. Only `container.py` imports concrete classes and wires them. |

Layering rule: `domain.py` and `interfaces.py` import nothing from the rest of the app. `api` depends on
`container`; `container` depends on everything; nothing depends on `api`.

## 4. Backend modules

### 4.1 `domain.py`
Plain frozen dataclasses shared across layers: `ParsedPage(text, page)`, `Source` (a retrieved chunk with
`doc_id, title, section, page, version, text, score`), `GuardResult(allowed, reason)`,
`Verification(passed, reason, coverage)`, and `DocumentMeta` (the metadata attached to every chunk of a document).

### 4.2 `interfaces.py`
| Protocol | Methods |
|---|---|
| `DocumentParser` | `parse(data: bytes) -> list[ParsedPage]` |
| `VectorStore` | `add(docs)`, `search(query, role, k) -> list[Source]`, `delete(doc_id)`, `list_documents()` |
| `AnswerGenerator` | `generate(question, sources) -> str` |
| `Verifier` | `verify(answer, sources) -> Verification` |
| `InputGuard` | `check(text) -> GuardResult` |

### 4.3 `rag/chunking.py`
`chunk_text(text, size, overlap, page)` splits on markdown headings, keeping a breadcrumb such as
`Leave Policy > Annual Leave`. Within a section it packs paragraphs up to `size` characters, carrying `overlap`
characters into the next chunk, and hard-splits paragraphs longer than `2 × size`. Each chunk's text is
prefixed with its section path so the heading context is embedded and shown to the model.

### 4.4 `rag/embeddings.py`
LangChain `Embeddings` implementations registered under `EMBEDDINGS`:
- `fastembed`: `FastEmbedEmbeddings`, local ONNX model, uses `query_embed` for queries.
- `hash`: `HashEmbeddings`, deterministic bag-of-words hashing (384 dims). Offline fallback and test double. Not semantically meaningful.

### 4.5 `rag/parsers.py`
`TextParser` (`.md`, `.txt`) and `PdfParser` (`.pdf`, one `ParsedPage` per page with page numbers, via `pypdf`).
`ParserRegistry.for_file(filename)` selects by extension and raises `ValueError` for unsupported types.
Scanned PDFs (no text layer) yield empty pages; OCR is out of scope.

### 4.6 `rag/store.py`: `QdrantPolicyStore`
Implements the read side (`Retriever`, `VectorStore`) and the write side (`VectorIndex`) directly on `qdrant_client`.
- **Named vectors.** Each chunk has a `dense` vector (cosine, size from the embedder) and, in hybrid mode, a `sparse` BM25 vector (Qdrant applies IDF at query time). The collection name encodes the embedding model and layout, for example `policy_chunks__fastembed_baai_bge_small_en_v1_5__v2_dense`, so changing either creates a new collection; migrate with `python -m app.rag.manage reindex`.
- `search` applies a **mandatory server-side filter**: `status == "active"` AND `allowed_roles` contains the caller's role or `"all"`. In hybrid mode the filter is applied inside both rankings, which are fused with Reciprocal Rank Fusion. Filtering happens inside Qdrant, so restricted chunks are never returned to the application.
- Every result carries `score` (what ranked it) and `relevance` (0..1, comparable across questions: the dense cosine similarity, or the reranker probability when reranking is on). The agent's answer/abstain decision uses `relevance`, because fused rank scores are not comparable across questions.
- `add_vectors(docs, vectors, sparse_vectors)`, `count_chunks`, `delete(doc_id)` and `list_documents()` as before; the payload layout (`page_content`, `metadata`) is unchanged.

### 4.6a Reranking (`rag/rerank.py`) and retrieval configuration
`RerankingRetriever` decorates any `Retriever`: it fetches `RERANK_FETCH_K` candidates (default 10), scores each with a cross-encoder
(`Xenova/ms-marco-MiniLM-L-6-v2`, local ONNX via FastEmbed, registered as `fastembed`; `overlap` is an offline test double), keeps the best `TOP_K`,
and sets both `score` and `relevance` to the reranker probability. Because that probability has its own scale, the agent threshold is
`MIN_RERANK_SCORE` (default 0.001) when a reranker is active and `MIN_RETRIEVAL_SCORE` (0.45, cosine) otherwise. The decision to make reranking the
default, keep hybrid opt-in, and the numbers behind it are in [phase2-retrieval-evaluation.md](phase2-retrieval-evaluation.md).

### 4.6b Evaluation suite (`app/eval/`, `backend/eval/`)
`python -m app.eval` runs the 60-case golden set (`eval/golden_set.json`, corpus in `eval/corpus` and `data/sample_docs`) through the **real**
`Container` on a throwaway Qdrant folder, one retrieval configuration at a time, and reports retrieval metrics (hit@k, MRR, recall), answer metrics
(answered, facts, citation precision), safety (refusals, leaks), threshold calibration and latency. `--configs dense:none,hybrid:none,dense:fastembed,hybrid:fastembed`
compares configurations; `--json` writes a report; `--min-pass-rate` makes it a CI gate. Modules: `cases.py` (golden-set loading), `metrics.py` (pure
functions), `harness.py` (stack builder), `runner.py`, `report.py`, `__main__.py`.

### 4.7 Ingestion pipeline (`rag/pipeline.py`, `rag/ingest.py`, `rag/text.py`)

`IngestionPipeline.run(filename, data, meta)` is a **generator of events**, one per stage, so callers (the UI,
tests, the blocking service) can observe progress. Every document goes through seven stages:

| # | Stage | What happens | Details reported |
|---|---|---|---|
| 1 | `receive` | Reject empty files; pick the parser by extension (unsupported type fails here) | filename, size, SHA-256 prefix, parser class, document metadata |
| 2 | `parse` | Extract text per page; fail if nothing extractable (e.g. scanned PDF) | pages, characters, text preview |
| 3 | `clean` | Strip front matter, normalize line endings, drop control characters, trim trailing spaces, collapse blank-line runs | characters before/after, removed count, operations |
| 4 | `chunk` | Heading-aware chunking (see 4.3); builds LangChain `Document`s with metadata | chunk count, size settings, min/avg/max length, section list, first 3 chunk previews |
| 5 | `embed` | Computes all vectors with the configured embedding model | model, vector count, dimensions, first 8 values of vector 0, its L2 norm |
| 6 | `store` | Counts then **deletes existing chunks for the `doc_id`**, upserts the new points | collection, previous chunks removed, points upserted, sample point IDs, payload fields |
| 7 | `verify` | Confirms the index holds exactly the expected chunk count, then runs a **self-retrieval check**: searches with chunk 0's text and confirms the top hit is this document (skipped for non-active documents) | chunks in index, self-retrieval result and score |

Event shapes (NDJSON on the wire):
```
{"type":"plan","doc_id":"...","steps":[{"id":"receive","label":"Receive and validate"}, ...]}
{"type":"step","id":"embed","status":"running"}
{"type":"step","id":"embed","status":"done","duration_ms":35,"details":{...}}
{"type":"step","id":"parse","status":"error","duration_ms":1,"error":"..."}   then   {"type":"failed","error":"..."}
{"type":"complete","doc_id":"...","chunks":3}
```
A failing stage stops the pipeline: later stages never run. Because stage 6 deletes before it adds, **re-ingesting a
`doc_id` replaces the document**; a failure before stage 6 leaves the previously indexed version untouched.

The pipeline depends on abstractions only: `VectorIndex` (write side: `add_vectors`, `delete`, `count_chunks`,
`search`), `ParserRegistry`, and LangChain `Embeddings`. Embeddings are computed in the pipeline (stage 5) and handed
to the index as ready vectors, which is what makes vector creation visible.

`IngestionService` is a thin layer over the pipeline: `ingest_bytes` runs it to completion (raising `ValueError` on a
failed stage; used by `POST /api/documents`) and `ingest_directory` loads `.md/.txt` samples using their front matter.

Front-matter format (read by `ingest_directory`; stripped from uploaded text in stage 3):
  ```
  ---
  doc_id: leave-policy
  title: Leave Policy
  department: HR
  version: 2.1
  allowed_roles: all            # or comma list: hr,compliance,admin
  ---
  ```

### 4.8 `providers/generators.py`
- `SYSTEM_PROMPT` instructs: answer only from numbered sources, cite `[n]` after every sentence, never invent numbers/dates/names, reply exactly `INSUFFICIENT_CONTEXT` if unanswerable.
- `LangChainGenerator(chat_model)`: wraps any LangChain chat model. Sends system prompt plus `Sources: [1] (Title - Section) text ...` and the question.
- `ExtractiveGenerator`: no LLM. Scores sentences of the top 3 sources by keyword overlap with the question, returns the best two with `[n]` citations, or `INSUFFICIENT_CONTEXT` if none overlap.
- `GENERATORS` registry: `ollama` (builds `ChatOllama(model, base_url, temperature)`), `extractive`.
- `ModelCatalog`: maps `ModelSpec.id` to a generator, built **lazily and cached**; exposes `specs()` and `default_id`; `get(None)` returns the default; unknown id raises `KeyError`.

### 4.9a Claim verification (`agents/claims.py`, `evidence.py`, `checkers.py`, `verifier.py`)
`split_claims` turns an answer into claims (one per sentence, with the sources it cites). A `ClaimChecker` judges each claim against **only the sources it cites**:
`SupportScoreChecker` (offline: numbers, negation parity per clause, sweeping words, clause-level wording coverage, optional cross-encoder veto) or
`LLMClaimChecker` (one chat call per answer returning JSON verdicts; provider errors surface as `JudgeError` without their message, and `FallbackChecker` drops back to the offline checker).
`ClaimVerifier` runs the rule checks first, then the claim checks, and returns a `Verification` with per-claim `ClaimCheck`s (verdict, cited sources, reason, strength), a
`confidence` (the weakest claim's strength, a heuristic) and a `hint` naming the unsupported claims. `VERIFIER_MODE` selects `rules`, `claims` (default) or `llm`.
Method, measurements (including why the first numbers were optimistic) and limits: [phase2-verifier-evaluation.md](phase2-verifier-evaluation.md).

### 4.9 `agents/components.py`
- `RegexInputGuard`: blocks prompt-injection phrases (e.g. "ignore previous instructions", "reveal your system prompt") and questions over 2000 characters.
- `CitationVerifier(min_coverage)`: see [section 6](#6-hallucination-prevention).

### 4.10 `agents/graph.py`: `PolicyAgent`
Constructed with a guard, a store, a `resolve_generator` callable, a verifier and thresholds; compiles the LangGraph on construction. `run(question, role, model_id)` returns the final `AgentState`. See the next section.

### 4.11 Identity: database, authentication and authorization (`db/`, `auth/`)
Users, roles and sessions live in **PostgreSQL, schema `auth`**. The full design is in
[section 7A](#7a-identity-authentication-and-authorization); in short:

| Module | Responsibility |
|---|---|
| `db/base.py`, `db/models.py` | SQLAlchemy models for the `auth` schema (roles, permissions, users, refresh tokens, audit log) |
| `db/session.py` | `Database` (engine and sessions), per-request `get_session` dependency |
| `db/bootstrap.py`, `db/manage.py` | Run migrations, seed roles/permissions/demo users, `create-admin` CLI |
| `alembic/` | Migration `0001` creating the schema |
| `auth/constants.py` | Role definitions with access levels, permissions, role-to-permission map, demo users |
| `auth/passwords.py` | `PasswordHasher` protocol, Argon2 implementation, password policy |
| `auth/tokens.py` | JWT access tokens and opaque refresh tokens (`TokenService`) |
| `auth/repositories.py` | `UserRepository`, `RoleRepository`, `RefreshTokenRepository`, `AuditRepository` |
| `auth/service.py` | `AuthService` (login, refresh, logout, change password) and `UserAdminService` (user CRUD) |
| `auth/deps.py` | FastAPI dependencies: `current_user`, `require_permission`, `require_level`, `require_roles` |
| `auth/router.py` | REST routes for `/auth/*`, `/api/me`, `/api/users`, `/api/roles`, `/api/audit-log` |
| `auth/errors.py`, `auth/schemas.py` | Framework-free service errors (carry an HTTP status) and request/response models |

### 4.12 `container.py`: composition root
`Container(settings)` builds the Qdrant client (server if `QDRANT_URL`, otherwise embedded at `QDRANT_PATH`), the embeddings via the registry, the store, ingestion service, model catalog and `PolicyAgent`. `get_container()` is `lru_cache`d and used as the FastAPI dependency, so tests and alternative deployments can substitute it.

### 4.13 `api/main.py`
Routes (see [section 10](#10-http-api-reference)). On startup (`lifespan`) it ingests `data/sample_docs` when the collection is empty and `AUTOLOAD_SAMPLES` is true.

## 5. Request flow: the agent graph

```mermaid
flowchart TD
  S([start]) --> guard
  guard -->|allowed| retrieve
  guard -->|blocked| abstain
  retrieve -->|sources above threshold| generate
  retrieve -->|none| abstain
  generate --> verify
  verify -->|passed| E([end])
  verify -->|failed, attempts < max| generate
  verify -->|failed, attempts = max| abstain
  verify -->|model said INSUFFICIENT_CONTEXT| abstain
  abstain --> E
```

`AgentState` fields: `question, role, model_id, sources, answer, verification, attempts, abstained,
abstain_reason, trace`.

| Node | Behavior |
|---|---|
| `guard` | Runs `InputGuard.check`. On block sets `abstained` and the reason. |
| `retrieve` | `retriever.search(question, role, TOP_K)`; keeps only chunks whose `relevance` is at least the active threshold (`MIN_RERANK_SCORE` with a reranker, otherwise `MIN_RETRIEVAL_SCORE`). Zero kept means abstain with "no relevant sources". The trace shows the threshold and the best relevance. |
| `generate` | Resolves the generator for `model_id` (default if none), generates an answer, increments `attempts`. |
| `verify` | Runs `Verifier.verify`. |
| `abstain` | Replaces the answer with a fixed message directing the user to HR; keeps the reason. |

Each node appends a human-readable line to `trace` (for example `retrieve: 5 found, 3 above threshold`,
`verify: fail (no citations)`). The API returns the trace and the UI shows it under "show steps".

`MAX_GENERATION_ATTEMPTS` (default 2) bounds the generate/verify loop so a misbehaving model cannot loop.

## 6. Hallucination prevention

Defenses are layered; failing any layer ends in abstention rather than a guess.

1. **Closed-book prompt.** The model sees only the retrieved sources and is told to answer from them or emit `INSUFFICIENT_CONTEXT`.
2. **Relevance threshold.** Chunks whose cross-encoder relevance is below `MIN_RERANK_SCORE` (default 0.001) are dropped, so off-topic and plausible-but-absent questions ("how do I bake bread?", "pet insurance") abstain before any model is called. On the golden set this raised correct refusals from 50% (cosine similarity alone cannot separate the cases) to 93%.
3. **Citation verifier** (`CitationVerifier`), applied to every non-abstaining answer:
   - at least one `[n]` citation exists;
   - every `n` is between 1 and the number of sources (no invented sources);
   - citation **coverage**, the share of sentences with a citation, is at least `MIN_CITATION_COVERAGE` (default 0.6);
   - every number in the answer (citation markers excluded) appears verbatim in the concatenated source text, which catches invented figures such as "30 days" when the policy says 24.
4. **Claim verifier** (`ClaimVerifier`, default mode `claims`): every sentence is checked against the sources it cites. Catches invented extra claims, sweeping wording, contradictions with negation and wrong citations offline; subtle meaning changes (swapped roles or numbers, flipped conditions, unit changes) need `VERIFIER_MODE=llm`. Measured on 40 held-out answers: rules only 5% of faulty answers caught, offline claims 40% (10% false alarms), LLM judge 100% (0% false alarms, about 17 s per answer).
5. **Bounded retry with feedback**, then abstain. A failed verification gives the generator a hint naming the unsupported claims; the abstention reason says why.
6. **Transparency.** The UI shows citations, the source passage, its relevance, the verification result, a confidence band, a per-claim check list and the step trace.

What this does *not* yet do: catch subtle meaning changes without the LLM judge; check that the answer actually addresses the question (a sabbatical question is still answered from the leave policy, with claims that are individually supported); and detect conflicts between document versions. Those are the remaining Phase 2 items.

## 7. Guardrails and access control

| Control | Where | Behavior |
|---|---|---|
| Prompt-injection screening | `RegexInputGuard` | Regex on known jailbreak phrasing; blocked questions abstain with reason. |
| Retrieved-text handling | prompt design | Sources are inserted as data under "Sources"; the system prompt restricts the model to them. Document-side injection scanning is not yet implemented. |
| Document RBAC | `QdrantPolicyStore.search` | Role filter enforced inside Qdrant; document-level `allowed_roles`. |
| Version/status filter | `QdrantPolicyStore.search` | Only `status == "active"` chunks are retrievable. |
| Endpoint permissions | `require_permission` | `documents:manage` for document endpoints, `chat:use` for chat and models, `users:*` and `audit:read` for administration. |
| Authentication | `current_user` | Bearer JWT on every route except `/auth/login`, `/auth/refresh`, `/auth/logout` and `/health`. |

A document's `allowed_roles` of `all` means everyone. Retrieval filters on the **role name**; role levels are not
used for document access, so a document restricted to `hr` is not visible to `admin` unless `admin` is listed.

## 7A. Identity: authentication and authorization

### 7A.1 Schema (`auth`, PostgreSQL)

```mermaid
erDiagram
  roles ||--o{ users : "role_id"
  roles ||--o{ role_permissions : ""
  permissions ||--o{ role_permissions : ""
  users ||--o{ users : "manager_id"
  users ||--o{ refresh_tokens : "user_id"
  users ||--o{ audit_log : "user_id"
```

| Table | Key columns |
|---|---|
| `roles` | `id`, `name` (unique), **`level`** (access level), `description` |
| `permissions` | `id`, `code` (unique, e.g. `users:manage`), `description` |
| `role_permissions` | `role_id`, `permission_id` (composite key, cascade delete) |
| `users` | `id` (UUID), `username` (unique, check: lowercase), `email` (unique, optional), `full_name`, `password_hash` (Argon2), `role_id`, `department`, `manager_id` (self reference, set null), `is_active`, `failed_login_attempts`, `locked_until`, `last_login_at`, `password_changed_at`, `created_at`, `updated_at` |
| `refresh_tokens` | `id`, `user_id` (cascade), `token_hash` (unique SHA-256), `family_id`, `expires_at`, `revoked_at`, `ip_address`, `user_agent` |
| `audit_log` | `id` (identity), `user_id` (set null), `username`, `action`, `success`, `ip_address`, `detail` (JSONB), `created_at` |

All timestamps are `timestamptz`. Constraint and index names follow a naming convention, and a test
(`test_schema.py`) checks that the Alembic migration and the models define identical tables, constraints and indexes.

### 7A.2 Access levels, roles and permissions

Access is two layered: a role has a numeric **level** (broader access, higher number) and a set of **permissions**
(what it may do). Endpoints check permissions; `require_level(n)` is available for rank-based checks.

| Role | Level | Permissions |
|---|---|---|
| `employee` | 10 | `chat:use` |
| `manager` | 20 | `chat:use` |
| `hr` | 30 | `chat:use`, `documents:manage`, `users:read` |
| `compliance` | 30 | `chat:use`, `documents:manage`, `users:read`, `audit:read` |
| `admin` | 100 | all of the above plus `users:manage` |

The definitions live in `auth/constants.py` and are upserted into the database at startup (`seed_reference_data`), so
changing a role's permissions is a code change plus restart. Adding a new role also requires adding it to `ROLE_NAMES`,
which validates document `allowed_roles`.

### 7A.3 Token model

| Token | Format | Lifetime | Storage |
|---|---|---|---|
| Access | HS256 JWT: `iss, sub` (user id), `username, role, level, type=access, jti, iat, exp` | 15 min (`ACCESS_TOKEN_MINUTES`) | Client only |
| Refresh | 48 random bytes, URL-safe | 7 days (`REFRESH_TOKEN_DAYS`) | Server stores only its SHA-256 hash |

- **Validation on every request.** `current_user` verifies signature, issuer, expiry and `type`, then **re-reads the user from the database**. Role changes, deactivation and permission changes therefore apply immediately, without waiting for token expiry.
- **Password change invalidates old tokens.** An access token whose `iat` is earlier than the user's `password_changed_at` is rejected (second resolution).
- **Refresh rotation.** Each `/auth/refresh` revokes the presented token and issues a new pair in the same `family_id`. Presenting an already-used token is treated as theft: the whole family is revoked and the attempt is audited as `refresh_reuse_detected`. Two simultaneous refreshes with the same token can trigger this (the web client serializes them).
- **Logout** revokes the token's family; `logout-all`, password change, password reset and deactivation revoke every refresh token of the user.

### 7A.4 Login protections
- Passwords are hashed with **Argon2id** (`argon2-cffi` defaults), and rehashed on login if parameters change.
- **Account lockout:** after `MAX_FAILED_LOGINS` (5) consecutive failures the account is locked for `LOCKOUT_MINUTES` (15); locked logins return 423 even with the right password. A successful login resets the counter.
- Unknown usernames and wrong passwords return the **same 401 body**, and a dummy hash is verified for unknown users so response time does not reveal which usernames exist.
- **Password policy** for new passwords: at least `PASSWORD_MIN_LENGTH` (10) characters, at most 128, not containing the username, not letters-only or digits-only. Seeded demo accounts bypass it.
- The client IP recorded is the direct peer address; `X-Forwarded-For` is ignored because it is client-controlled. Behind a trusted reverse proxy, configure the proxy-aware address handling in the server instead.

### 7A.5 Administration rules
- Only holders of `users:manage` create, update, deactivate users or reset passwords.
- A user **cannot change their own role or deactivate themselves**, which prevents an admin from locking the system out.
- `DELETE /api/users/{id}` is a **soft delete** (`is_active=false` plus session revocation) so history and the audit trail stay intact; re-activate with `PATCH {"is_active": true}`.
- Manager assignments are validated: the manager must exist, cannot be the user, and cannot create a reporting cycle.
- Username and email uniqueness is enforced by the database (409 on conflict; emails are compared case-insensitively).
- Every login outcome, refresh, logout, password change and administrative action is written to `audit_log` with the actor, target, IP and details. Passwords and tokens are never logged.

### 7A.6 Bootstrapping
1. Start Postgres (`docker compose up -d postgres`) or point `DATABASE_URL` at your own server.
2. The API applies Alembic migrations on startup (`AUTO_MIGRATE=true`), or run `python -m app.db.manage migrate`.
3. With `SEED_DEMO_USERS=true` and an empty users table, five demo accounts are created for local development.
   In any shared environment set `SEED_DEMO_USERS=false` and create the first administrator with
   `python -m app.db.manage create-admin --username <name> --email <email>` (prompts for the password).

### 7A.6a Standalone SQL scripts
The [`db/`](../db/README.md) folder holds plain-SQL equivalents for DBAs or manual setup: `schema.sql` (the migration
rendered as SQL and stamped with the Alembic revision), `sample_data.sql` (roles, permissions, 9 sample users with
Argon2 hashes, idempotent) and `drop_schema.sql`. They are generated by `backend/app/db/sqlgen.py`
(`python -m app.db.manage export-sql`), so the code stays the single source of truth, and `python -m app.db.manage run-sql FILE`
executes them without needing `psql`. `test_sql_scripts.py` fails if the files are stale, loads the sample data into SQLite
and verifies counts, foreign keys, manager links, idempotency and every sample password hash.

### 7A.7 Testing against Postgres and SQLite
The suite runs on a throwaway **SQLite** file by default (the `auth` schema is mapped away), so it works offline. Set
`TEST_DATABASE_URL=postgresql+psycopg://policy:policy@localhost:5433/policy_test` to run the same 144 tests against
PostgreSQL. Both have been run: on **PostgreSQL 16.15** the migration builds the schema from scratch (identical to
`schema.sql`), `JSONB`, identity columns and constraints behave as designed, and every test passes. Running against
Postgres found nothing that SQLite had hidden, but it did lead to storing absent audit details as SQL `NULL` instead of
JSON `null`.

## 8. Model selection

Two levels, one source of truth (`ModelSpec`):

```python
ModelSpec(id="llama3.1-8b", label="Llama 3.1 8B (Ollama)", provider="ollama",
          name="llama3.1:8b", temperature=0.0, default=True)
```

**Config level**
- Defaults live in `config.py` (`DEFAULT_MODELS`): Llama 3.1 8B (default), Qwen 2.5 7B, Mistral 7B (all Ollama, local), one **Gemini** model (Google, cloud) and `extractive`.
- **Gemini** uses `langchain-google-genai`. The single default is `gemini-3.5-flash-lite`, the one found to work with the project's key (real question answered, cited and verified through the app in about 25 s). Google retires models quickly: the 2.5 family returned "no longer available to new users" and the `-latest` aliases timed out or hit quota on the same key, so none of those are defaults. Check [Google's model list](https://ai.google.dev/gemini-api/docs/models) and your key's quota, then add, replace or pin entries in `MODELS_CONFIG` (a `provider: "gemini"` entry with the model `name`); no code change is needed.
- The key comes from `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) in `backend/.env`. Without it the Gemini options are still listed but marked unavailable.
- Override with `MODELS_CONFIG=/path/models.json`, a JSON array of `ModelSpec` objects. Example:
  ```json
  [
    {"id": "qwen-14b", "label": "Qwen 2.5 14B", "provider": "ollama", "name": "qwen2.5:14b", "default": true},
    {"id": "extractive", "label": "Offline", "provider": "extractive"}
  ]
  ```
- Embeddings are chosen only here (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`) because a collection's vector size is fixed. The collection name embeds the provider and model (for example `policy_chunks__fastembed_baai_bge_small_en_v1_5`), so changing embedding models creates a **new, empty collection** that is re-populated from the sample docs on startup. Upload documents again if you ingested your own.

**Application level**
- `GET /api/models` returns the default and, for each model, `{id, label, provider, local, available, unavailable_reason}`. The UI groups them into **Local** and **Cloud**, disables unavailable ones and shows the reason, and shows a "cloud model" badge while one is selected.
- `POST /api/chat` accepts an optional `model_id`. Unknown id returns 400. A model that is configured but unusable (for example Gemini without a key) returns 503 with the reason. A provider failure during generation (unreachable, quota, invalid key) returns 503 with only the exception *type* and a generic hint, so provider error text, which can contain key fragments, never reaches the client.

**Data handling for cloud models.** When a Gemini model is selected, the user's question and the retrieved policy passages are sent to Google. Retrieval still applies the caller's role and document-status filters first, so only passages that user may read are sent, but the text does leave your infrastructure. Use the local models for documents that must not leave it, and review Google's data-use terms for your API tier before enabling Gemini on confidential policies. Embeddings are always local.
- The chosen model id is echoed in the response and shown under each answer.

## 9. Data model and Qdrant storage

One Qdrant point per chunk. `langchain-qdrant` stores the text as `page_content` and everything else under
`metadata`:

| Field (`metadata.*`) | Type | Purpose |
|---|---|---|
| `doc_id` | keyword | Replace/delete a document |
| `title` | string | Citation label |
| `department` | string | Informational; filter-ready |
| `version` | string | Shown in citations |
| `status` | keyword | `active` is retrievable; others are not |
| `allowed_roles` | keyword list | RBAC filter |
| `section` | string | Heading breadcrumb |
| `page` | int or null | PDF page number |

Vector: dense, cosine, dimension from the embedder (384 for bge-small). Embedded mode stores data under
`backend/data/qdrant/` (git-ignored); only one process may open it at a time. Use the Qdrant server
(`QDRANT_URL`) for multiple workers.

## 10. HTTP API reference

Routes need `Authorization: Bearer <access token>` except `/auth/login`, `/auth/refresh`, `/auth/logout` and `/health`.
Authentication and user administration are described in [section 7A](#7a-identity-authentication-and-authorization); the
tables below list every route.

| Method and path | Role | Description |
|---|---|---|
| `POST /auth/login` | none | Body `{username, password}`. Returns `{access_token, refresh_token, token_type, expires_in, user}`. 401 bad credentials (same body for unknown user), 403 disabled account, 423 locked. |
| `POST /auth/refresh` | none | Body `{refresh_token}`. Rotates: returns a new token pair and revokes the old refresh token. 401 if invalid, expired, revoked or replayed (replay revokes the whole chain). |
| `POST /auth/logout` | none | Body `{refresh_token}`. Revokes the session. Always 204 (idempotent). |
| `POST /auth/logout-all` | any user | Revokes every refresh token of the caller. 204. |
| `POST /auth/change-password` | any user | Body `{current_password, new_password}`. 204; signs out all sessions. 401 wrong current password, 422 policy violation. |
| `GET /api/me` | any user | `{id, username, name, role, level, department, permissions}`, rebuilt from the database. |
| `GET /api/users` | `users:read` | Query `q`, `role`, `active`, `offset`, `limit` (1-200). Returns `{items, total, offset, limit}`. |
| `POST /api/users` | `users:manage` | Body `{username, password, full_name, email?, role?, department?, manager_id?}`. 201. 409 duplicate, 422 validation. |
| `GET /api/users/{id}` | `users:read` | One user. 404 if unknown. |
| `PATCH /api/users/{id}` | `users:manage` | Partial update of `full_name, email, role, department, manager_id, is_active`. 403 when changing your own role or active flag. |
| `DELETE /api/users/{id}` | `users:manage` | Soft delete (deactivate and revoke sessions). Returns the user. |
| `POST /api/users/{id}/reset-password` | `users:manage` | Body `{new_password}`. 204; signs the user out everywhere. |
| `GET /api/roles` | `users:read` | Roles with level and permissions. |
| `GET /api/audit-log` | `audit:read` | Query `action`, `username`, `offset`, `limit`. Newest first. |
| `GET /api/models` | `chat:use` | `{default, models: [{id, label, provider, local, available, unavailable_reason}]}`. |
| `POST /api/chat` | any | Body `{question, model_id?}`. See response below. |
| `GET /api/documents` | admin, hr, compliance | Documents with chunk counts. |
| `POST /api/documents` | admin, hr, compliance | Multipart: `file`, `title`, `doc_id`, `department`, `version`, `allowed_roles` (comma list or `all`), `status` (`active`, `inactive`, `draft`). Re-using a `doc_id` replaces the document. Returns `{doc_id, chunks}`. 400 for invalid metadata, unsupported file types or other pipeline failures. |
| `POST /api/documents/ingest` | admin, hr, compliance | Same form fields. Runs the pipeline and **streams NDJSON events** (`application/x-ndjson`), one line per stage transition (see 4.7). Metadata problems return 400 before streaming; pipeline failures arrive in-stream as a `failed` event with HTTP 200. |
| `DELETE /api/documents/{doc_id}` | admin, hr, compliance | Removes all chunks of the document. |
| `GET /health` | none | `{status: "ok"}`. |

`POST /api/chat` response:
```json
{
  "answer": "Employees receive 10 days of paid sick leave per year [1].",
  "abstained": false,
  "abstain_reason": null,
  "model_id": "extractive",
  "sources": [{"doc_id": "leave-policy", "title": "Leave Policy", "section": "Leave Policy > Sick Leave",
               "page": null, "version": "2.1", "text": "...", "score": 0.81}],
  "verification": {"passed": true, "reason": "grounded", "coverage": 1.0},
  "trace": ["guard: ok", "retrieve: 5 found, 5 above threshold", "generate: attempt 1", "verify: pass (grounded)"]
}
```
When `abstained` is true, `answer` is the fixed fallback message and `sources` is empty.

Error codes: 400 unknown model or file type, 401 missing/invalid token, 403 missing permission, 423 locked account, 503 model
unavailable.

Example:
```bash
TOKEN=$(curl -s -X POST localhost:8010/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"alice123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST localhost:8010/api/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question":"How many sick days do I get?","model_id":"extractive"}'
```

## 11. Configuration reference

Set as environment variables or in `backend/.env` (see `.env.example`). Names are case-insensitive.

| Variable | Default | Description |
|---|---|---|
| `MODELS_CONFIG` | none | JSON file overriding the model list |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | none | Enables the Gemini models. Server-side only; never sent to the browser. Empty means not configured |
| `QDRANT_URL` | none | Qdrant server URL; if unset, embedded storage is used |
| `QDRANT_PATH` | `backend/data/qdrant` | Embedded storage directory |
| `QDRANT_COLLECTION_PREFIX` | `policy_chunks` | Prefix of the collection name |
| `EMBEDDING_PROVIDER` | `fastembed` | `fastembed` or `hash` |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Model for the embedding provider |
| `RETRIEVAL_MODE` | `dense` | `dense`, or `hybrid` (dense + BM25 keywords fused with RRF; opt-in, no gain measured on the evaluation corpus) |
| `SPARSE_PROVIDER` / `SPARSE_MODEL` | `fastembed` / `Qdrant/bm25` | Keyword vectors for hybrid mode (`hash` is an offline fallback) |
| `RERANKER_PROVIDER` | `fastembed` | `fastembed` (cross-encoder), `overlap` (offline test double) or `none` |
| `RERANKER_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | Cross-encoder (80 MB). Larger options include `BAAI/bge-reranker-base` |
| `RERANK_FETCH_K` | 10 | Candidates handed to the reranker (10 vs 20: same accuracy, about 60% of the latency) |
| `TOP_K` | 5 | Chunks kept per question |
| `MIN_RETRIEVAL_SCORE` | 0.45 | Relevance threshold when **no** reranker is used (cosine similarity) |
| `MIN_RERANK_SCORE` | 0.001 | Relevance threshold when a reranker is used (probability). Re-tune with `python -m app.eval` after changing the model |
| `MIN_CITATION_COVERAGE` | 0.6 | Minimum share of cited sentences |
| `MAX_GENERATION_ATTEMPTS` | 2 | Generate/verify loop bound |
| `VERIFIER_MODE` | `claims` | `rules`, `claims` (offline claim-by-claim checks) or `llm` (LLM judge with offline fallback; sends the answer and cited passages to the judge model) |
| `VERIFIER_MODEL_ID` | `gemini-3.5-flash-lite` | Catalog model used as the judge in `llm` mode |
| `VERIFIER_MIN_LEXICAL` / `VERIFIER_MIN_CROSS_ENCODER` | 0.5 / 0.01 | Share of a claim's content words that must be in the cited text; minimum cross-encoder probability |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 900 / 150 | Chunking in characters |
| `DATABASE_URL` | `postgresql+psycopg://policy:policy@localhost:5432/policy_copilot` | Identity database; a `sqlite:///` URL works for tests and offline development |
| `AUTO_MIGRATE` | true | Apply Alembic migrations (Postgres) or create tables (SQLite) at startup |
| `SEED_DEMO_USERS` | true | Create the five demo users when the users table is empty. Set false outside local development |
| `JWT_SECRET` | `dev-only-change-me` | **Change outside local development** (a startup warning is logged while it is the default) |
| `JWT_ISSUER` | `policy-copilot` | `iss` claim, verified on every request |
| `ACCESS_TOKEN_MINUTES` | 15 | Access token lifetime |
| `REFRESH_TOKEN_DAYS` | 7 | Refresh token lifetime |
| `MAX_FAILED_LOGINS` / `LOCKOUT_MINUTES` | 5 / 15 | Account lockout |
| `PASSWORD_MIN_LENGTH` | 10 | Minimum length for new passwords |
| `SAMPLE_DOCS_DIR` | `backend/data/sample_docs` | Startup ingestion source |
| `AUTOLOAD_SAMPLES` | true | Ingest samples when the collection is empty |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed browser origins (JSON list) |

Tuning notes: raising `MIN_RETRIEVAL_SCORE` makes the system abstain more and answer fewer borderline
questions; scores depend on the embedding model, so re-tune after changing it. The `hash` embedder produces much
lower scores, so tests set `MIN_RETRIEVAL_SCORE=0.15`.

## 12. Frontend

React 18 + Vite, styled with **Tailwind CSS 4** (`@tailwindcss/vite`). In dev, Vite proxies `/api` and `/auth` to
`http://localhost:8010` (`vite.config.js`).

| File | Role |
|---|---|
| `src/api.js` | `fetch` wrapper; keeps the JWT in `sessionStorage`; silent refresh on 401; `login, logout, me, models, chat, documents, ingest`. Errors carry the server `detail`. |
| `src/index.css` | Tailwind entry, **theme tokens** (light and dark values), the `@theme` mapping to utilities, and a few reusable classes (`card`, `field`, `btn`, `btn-primary`, `btn-ghost`, `badge`) |
| `src/theme.js` | `useTheme()` hook: light/dark state, persistence, system-preference following |
| `src/App.jsx` | Session bootstrap (`/api/me` and `/api/models`), chat state, view switching |
| `src/components/Header.jsx` | Sticky header: logo, Chat/Ingestion tabs (only with `documents:manage`), model picker (grouped local/cloud), cloud badge, user chip, theme toggle, sign-out |
| `src/components/ThemeToggle.jsx` | Accessible dark/light switch (`role="switch"`, `aria-checked`) |
| `src/components/Login.jsx` | Sign-in card with demo-account shortcuts, inline error, loading state |
| `src/components/ChatView.jsx` | Empty state with suggested questions, message list, typing indicator, sticky composer |
| `src/components/Message.jsx` | Answers with clickable `[n]` citation chips, expandable source passages with similarity bars, verified and model badges, collapsible step trace, abstained and error styling |
| `src/components/IngestPage.jsx` | Ingestion tab: drag-and-drop upload form (title and ID auto-filled from the filename), runs `api.ingest`, applies each streamed event to the step list, refreshes the document list |
| `src/components/StepTimeline.jsx` | Vertical timeline of the pipeline stages with status dots, durations and expandable details (key/value rows, chunk previews, vector preview). Failed stages open automatically |
| `src/components/DocumentsTable.jsx` | Indexed documents with status and role badges and delete; scrolls horizontally on small screens |
| `src/components/icons.jsx` | Inline SVG icon set (no icon dependency) |

The token lives in `sessionStorage` (cleared when the tab closes). Chat history is held in component state only.

### Theming
- **Class-based dark mode.** Tailwind's `dark:` variant is bound to a `dark` class on `<html>` (`@custom-variant dark` in `index.css`).
- **Semantic tokens, not raw colors.** Every color is a CSS variable defined twice in `index.css` (`:root` for light, `.dark` for dark) and exposed to Tailwind through `@theme inline` (`bg-surface`, `text-muted`, `border-border`, `bg-accent`, `bg-success-soft`, ...). Components never use hard-coded palette colors, so a theme is just a set of token values and a new theme (or brand color change) is a CSS-only edit.
- **Toggle behavior.** The header (and the sign-in page) has a light/dark switch. The first visit follows the operating-system setting (`prefers-color-scheme`) and keeps following it until the user flips the switch; the choice is then saved in `localStorage` (`theme`). If storage is blocked the toggle still works for the session.
- **No flash on load.** A tiny inline script in `index.html` applies the saved or system theme before first paint.
- **Native controls follow the theme** through `color-scheme` (scrollbars, selects, date pickers).
- **Accessibility.** Visible keyboard focus rings, `aria-*` on toggles, expanders and alerts, `prefers-reduced-motion` support, text colors chosen for readable contrast in both themes.
- **Responsive.** The header reflows to three compact rows on phones, tables scroll inside their card, and no page-level horizontal scroll (checked at 375 px).

## 13. Extending the system

**Add an LLM provider** (for example vLLM or any OpenAI-compatible server)
1. Create the generator, reusing `LangChainGenerator` with any LangChain chat model.
2. Register it in `providers/generators.py`:
   ```python
   @GENERATORS.register("vllm")
   def _vllm(spec: ModelSpec, settings: Settings):
       from langchain_openai import ChatOpenAI
       return LangChainGenerator(ChatOpenAI(model=spec.name, base_url=settings.vllm_url, api_key="x"))
   ```
3. Add a `ModelSpec` with `provider="vllm"` to the config list. The UI picks it up automatically.

**Add an embedding provider**: implement a LangChain `Embeddings` class and `@EMBEDDINGS.register("name")`; set `EMBEDDING_PROVIDER=name`.

**Add a file type**: write a class with `parse(data) -> list[ParsedPage]` and register it in `default_parsers()`, for example `.register((".docx",), DocxParser())`.

**Swap the vector store**: implement the `VectorStore` Protocol and construct it in `container.py`. The agent and ingestion service need no change.

**Add a stronger verifier or guard**: implement `Verifier` or `InputGuard` (for example an LLM-based entailment check, or a classifier) and pass it in `container.py`. To chain several, write a small composite that implements the same Protocol.

**Add a graph node or agent**: add a method to `PolicyAgent`, register it in `_build()`, and add edges. Keep node logic over injected abstractions so it stays testable.

## 14. Testing

```bash
cd backend && .venv/Scripts/python -m pytest      # 144 tests (+1 opt-in quality gate: RUN_EVAL=1)
```

`tests/conftest.py` sets environment variables **before** importing the app: `EMBEDDING_PROVIDER=hash`,
`QDRANT_PATH` to a temp directory, `MIN_RETRIEVAL_SCORE=0.15`, and `RERANKER_PROVIDER=none` (reranking and hybrid retrieval are tested separately with offline doubles). Tests therefore run offline in about a second, using the
`extractive` model.

| File | Covers |
|---|---|
| `test_units.py` | Chunk sizing and section breadcrumbs; verifier accept/reject cases (no citation, bad index, ungrounded number, abstain); injection guard; extractive citations; `Registry`; `ModelCatalog` default and caching |
| `test_api.py` | Auth required; model list; grounded cited answer; off-topic abstention; injection blocked; unknown model 400; **RBAC** (employee cannot see the HR-restricted document, HR can); document endpoints restricted by role |
| `test_pipeline.py` | Text cleaning and front matter; all seven stages emitted in order with JSON-serializable events; chunk, embedding (384 dims, 8-value preview), store and verify details; re-ingest replaces rather than duplicates; pipeline stops at the failing stage (unsupported type, empty file); inactive documents skip self-retrieval; an ingested document is found by chat; `/api/documents/ingest` returns NDJSON, reports failures in-stream, enforces RBAC and validates `doc_id`, roles and status; delete removes chunks |
| `test_auth.py` | Login (tokens, claims, case-insensitive username, identical errors for unknown user and wrong password); lockout and counter reset; 9 forged or invalid token cases (expired, wrong secret, wrong issuer, wrong type, unknown user, `alg=none`, refresh token as bearer, garbage); refresh rotation and replay detection; logout and logout-all; change password and admin reset (old tokens and sessions die); role-and-permission matrix across employee, HR, compliance and admin; 401 versus 403; immediate effect of role change and deactivation; self-lockout protection; user validation (policy, duplicates, roles, managers, cycles); filtering and pagination; audit log contents |
| `test_schema.py` | Alembic migration and SQLAlchemy models define the same tables, constraints and indexes (offline SQL generation); everything is in the `auth` schema |
| `test_sql_scripts.py` | `/db` scripts match the generator; schema script creates every table and stamps Alembic; drop script touches only `auth`; sample data loads (SQLite), has consistent counts, foreign keys, role levels and manager links, is idempotent, reproducible, and every password verifies |
| `test_models.py` | Gemini options in the default catalog (cloud-labelled, open-source model stays the default); availability follows the API key (either env name, empty means unset); catalog refuses Gemini without a key and builds it with one (no network); `MODELS_CONFIG` can pin a Gemini id; content-part parsing; `/api/models` fields; 503 with a clear reason without a key; end-to-end chat through a fake Gemini; provider failures never leak error text or key fragments |
| `test_retrieval.py` | Collection names per layout; threshold follows the scorer; measured defaults; relevance fallback; reranker reorders, truncates, sets relevance and keeps texts; reranked abstention uses the reranker score and reports the threshold in the trace; hybrid store returns cosine relevance plus fused score, finds exact identifiers, still enforces role and status filters, requires sparse vectors on write; dense store has no keyword vectors; the embed stage reports keyword vectors only in hybrid mode |
| `test_claims.py` | Claim extraction (citations after the full stop, fragments); stemmer, numbers, coverage, clauses, negation and sweeping-word helpers; each fault type flagged and faithful paraphrases supported; two-clause claims with a negation not misread; reasons; cross-encoder veto; thresholds; verifier output (confidence, hint, rule pass-through, abstention); LLM judge (JSON mapping, one call per answer, no call for uncited claims, bad replies, provider errors never leak, fallback counting); the agent retries with the verifier's feedback and then passes, or abstains with the reason; API returns claim checks and confidence; container selects the verifier by mode and falls back offline when the judge model is unavailable |
| `test_verifier_eval.py` | Both labeled datasets resolve their sources, have unique ids and consistent labels, faithful answers are well formed; the held-out set contains the subtle fault types; metric functions; regression floors (dev 90% caught, held-out 35% caught with at most 15% false alarms); claim checks beat rules-only by more than 25 points on both sets; threshold calibration |
| `test_eval.py` | Metric functions; golden-set integrity (unique ids, known documents and categories, expected documents active, **every expected fact present in its expected documents**, risk categories covered); an offline end-to-end run where leaks stay at zero and injection cases are always refused; threshold override reaches the agent; opt-in **quality gate with the real models** (`RUN_EVAL=1`) requiring pass rate 90%, refusal rate 85%, answer rate 95%, hit@k 98% and zero leaks |

Not covered by automated tests: the Ollama path (needs a running server), real-embedding relevance, the
frontend, PDF parsing, and Postgres in CI (the suite uses SQLite unless `TEST_DATABASE_URL` is set; it has been run on
Postgres 16.15 by hand). Verified manually: the full chat flow and the ingestion flow in the browser with real
embeddings (HR user uploads a markdown file, watches the seven stages, then asks a question about it).

## 15. Running and operating

See the [README](../README.md) for setup commands. Operational notes:
- First start downloads the embedding model (needs internet once; cached afterwards) and indexes the sample documents.
- Embedded Qdrant allows one process; run `uvicorn` with a single worker or switch to the Qdrant server.
- With Ollama, run `ollama pull llama3.1:8b` (or the models you configure). Responses take seconds on CPU.
- Port 8010 is used for the API to avoid clashing with other local apps on 8000.
- Do not deploy as-is: set `SEED_DEMO_USERS=false`, create an administrator with `create-admin`, set a strong `JWT_SECRET`, restrict CORS, and add TLS (and a proxy-aware client-IP setup if behind a reverse proxy).

## 16. Known limitations and roadmap

| Limitation | Planned phase |
|---|---|
| Hybrid search is built but unproven: no gain on the 15-document evaluation corpus | Re-evaluate on a larger corpus |
| The reranker threshold (0.001) was tuned on the same 60 golden cases it is scored on; reranking adds about 280 ms per question on CPU | Grow the golden set (feedback buttons), re-calibrate |
| The offline claim checks miss subtle meaning changes (10 of 10 on the held-out set); the LLM judge catches them but adds about 17 s and a cloud call per answer | Choose per deployment (`VERIFIER_MODE`); a local judge model would remove the cloud call |
| The verifier was measured on 40 hand-written held-out answers and not on live LLM output | Run it on real generations once a local or cloud LLM is part of the evaluation |
| The answer is not checked for relevance to the question (the sabbatical case) | Phase 2, next |
| No conflict detection between document versions | Phase 2, next |
| Extractive mode can pick the wrong sentence (3 of 60 golden cases still fail: one reranker miss, one extractive miss, one plausible-but-absent question) | LLM generator plus claim-level verifier (Phase 2, next) |
| Single-shot Q&A; no conversation memory or query rewriting | Phase 2 |
| One agent graph; no router, HR-operations or escalation agents | Phase 3 |
| Regex-only guardrails; no PII redaction, no document-side injection scanning | Phase 4 |
| Observability is the per-request trace only; no persistence, cost or quality metrics | Phase 5 (Langfuse or Phoenix, audit log, dashboard) |
| In-memory chat history; no admin UI for users (the REST API exists); no per-IP rate limiting, MFA or OIDC | Phase 3 to 6 |
| The real-model quality gate is opt-in (`RUN_EVAL=1`), not yet run in CI; no model-based groundedness judge | Phase 2, next |

## 17. Requirements traceability

Status of the requirement IDs in [requirements-analysis.md](requirements-analysis.md):

| Requirement | Status | Notes |
|---|---|---|
| FR-ING-1, 2, 3, 4, 5, 6 | Done (partial for 5) | md/txt/pdf; versions stored and `status` filtered, no automatic supersede workflow |
| FR-ING-8 | Done | Step-by-step pipeline view in the Ingestion tab |
| FR-ING-7 | Not started | Document-side injection scan |
| FR-RAG-1 | Done (opt-in) | Hybrid dense + BM25 with RRF behind `RETRIEVAL_MODE=hybrid`; dense is the measured default |
| FR-RAG-2, 5 | Done | Role/status filters; section/page/title returned |
| FR-RAG-3 | Done | Cross-encoder reranking, default on |
| FR-RAG-6 | Done | Top-k, fetch-k, thresholds and models configurable |
| FR-RAG-4 | Not started | Query rewriting and conversation-aware follow-ups |
| FR-HAL-1, 2, 4, 7 | Done | Closed-book prompt, citations, abstain, number check |
| FR-HAL-3 | Done (limits documented) | Claim-by-claim verifier: offline checks by default, LLM judge optional; subtle meaning changes need the LLM judge |
| FR-HAL-6 | Done | Confidence band (heuristic), relevance and version shown per source |
| FR-HAL-5, 8 | Not started | Version conflicts and user feedback |
| FR-AGT-7, 8 | Done | Explicit graph, bounded attempts |
| FR-AGT-1 to 6, 9 | Not started | Router, HR-ops, escalation, approvals |
| FR-GRD-1, 4 | Done / partial | Regex injection check; document RBAC and permission-based endpoint checks |
| FR-GRD-2, 3, 5 to 8 | Not started | |
| FR-OBS-1 | Partial | Step trace per request |
| FR-OBS-6 | Partial | Golden-set evaluation with CLI, JSON reports and an opt-in quality gate; not yet in CI |
| FR-OBS-2 to 5, 7, 8 | Not started | |
| FR-UI-1 (streaming) | Partial | Chat without streaming |
| FR-UI-2, 3, 7 | Partial | Citations and source view, step trace; no feedback button |
| FR-UI-5 | Partial | Document upload, list and delete with live ingestion steps; no version history or guardrail settings |
| FR-AUTH-1 | Partial | Database-backed JWT login with refresh rotation; no OIDC |
| FR-AUTH-2, 3 | Done | Five roles with access levels and permissions in Postgres; role name drives retrieval filters, permissions gate endpoints |
| NFR-8, 9 | Partial | Typed, modular; tests exist; Docker Compose provides Qdrant and Ollama only |
