# Requirements Analysis: Enterprise Policy, Compliance & HR Operations Copilot

| | |
|---|---|
| Version | 0.1 (draft) |
| Date | 2026-10-29 |
| Owner | Vicky Jadhav |
| Status | For review |

---

## 1. Purpose and Background

Employees struggle to find accurate answers in scattered policy documents (HR handbook, IT and
security policy, code of conduct, legal and compliance guidelines). HR teams spend significant time
answering repetitive questions and processing routine requests. Generic chatbots are unsuitable
because they hallucinate, leak sensitive data and cannot be audited.

This system is an AI copilot that:
1. Answers policy and compliance questions **only from approved documents**, with citations.
2. Performs **HR operations** (leave, onboarding, letters, benefits queries) through controlled agent workflows.
3. Is safe by design (guardrails) and transparent by design (observability and audit).

It also serves as a reference implementation of: RAG, hallucination prevention, multi-agent
orchestration, guardrails and observability.

## 2. Goals and Non-Goals

### Goals
- G1. Grounded answers with verifiable citations for >= 95% of in-scope questions.
- G2. Abstain ("I don't know / contact HR") rather than guess when evidence is weak.
- G3. Automate common HR operations with human approval where required.
- G4. Enforce role-based access to documents and actions.
- G5. Full traceability of every answer and action (who, what, which sources, which agents, cost).

### Non-Goals (v1)
- Legal advice or binding compliance determinations.
- Replacing the HRIS or payroll system of record (integrate through mock/stub connectors first).
- Multilingual support, voice and mobile-native apps.
- Fine-tuning custom models.

## 3. Stakeholders and Users

| Persona | Needs |
|---|---|
| Employee | Fast, correct policy answers; self-service HR requests |
| Manager | Approve leave and requests; team-policy questions |
| HR Operations | Reduced ticket volume; review queue; letter generation |
| Compliance / Legal Officer | Control over approved sources, audit trail, policy version control |
| IT / Security | Data protection, access control, incident visibility |
| Platform Admin / AI Engineer | Ingestion management, evaluation, monitoring, cost control |

## 4. Scope

### In scope
- **Policy and compliance Q&A:** HR, IT security, code of conduct, data privacy, travel and expense, anti-harassment, regulatory guidelines.
- **HR operations:** leave balance and application, onboarding checklist, benefits FAQ, employment/experience letter drafts, holiday calendar, escalation to HR ticket.
- **Admin:** document ingestion, versioning, evaluation dashboard, guardrail configuration.

### Out of scope
- Payroll calculation, performance reviews, recruitment, and termination decisions.

## 5. Functional Requirements

Priority: **M** = Must, **S** = Should, **C** = Could.

### 5.1 Document Ingestion and Knowledge Management
| ID | Requirement | Pri |
|---|---|---|
| FR-ING-1 | Upload PDF, DOCX, MD, TXT and HTML policy documents | M |
| FR-ING-2 | Parse, clean and chunk documents preserving headings and section structure | M |
| FR-ING-3 | Store metadata: department, document type, version, effective date, owner, access roles | M |
| FR-ING-4 | Generate dense and sparse embeddings and index in Qdrant | M |
| FR-ING-5 | Document versioning; superseded versions excluded from answers by default | M |
| FR-ING-6 | Re-ingest and delete documents with index consistency | M |
| FR-ING-7 | Scan documents for embedded prompt injection before indexing | S |
| FR-ING-8 | Show ingestion status and errors in admin UI | S |

### 5.2 Retrieval (RAG)
| ID | Requirement | Pri |
|---|---|---|
| FR-RAG-1 | Hybrid retrieval (dense + sparse) over Qdrant | M |
| FR-RAG-2 | Metadata filtering by user role, department, effective version | M |
| FR-RAG-3 | Reranking of top-k candidates | S |
| FR-RAG-4 | Query rewriting and conversation-aware follow-up resolution | S |
| FR-RAG-5 | Return source passage, document name, section and page for each chunk | M |
| FR-RAG-6 | Configurable chunk size, overlap, top-k and score thresholds | S |

### 5.3 Answer Generation and Hallucination Prevention
| ID | Requirement | Pri |
|---|---|---|
| FR-HAL-1 | Answers must be generated only from retrieved context | M |
| FR-HAL-2 | Every factual claim carries an inline citation to a retrieved chunk | M |
| FR-HAL-3 | Groundedness verifier checks each claim against its cited source | M |
| FR-HAL-4 | If retrieval confidence or groundedness is below threshold, abstain and offer HR escalation | M |
| FR-HAL-5 | Detect and surface conflicting policies/versions rather than silently choosing | S |
| FR-HAL-6 | Display a confidence indicator and "last updated" date of sources | S |
| FR-HAL-7 | Verify numbers, dates and entitlements (e.g., leave days) against source text or tool output | M |
| FR-HAL-8 | User feedback (helpful / wrong / outdated) captured per answer | S |

### 5.4 Multi-Agent Orchestration
| ID | Requirement | Pri |
|---|---|---|
| FR-AGT-1 | **Router agent** classifies intent: policy Q&A, HR operation, out-of-scope, escalation | M |
| FR-AGT-2 | **Retriever agent** plans queries and performs retrieval | M |
| FR-AGT-3 | **Answer agent** drafts a cited response | M |
| FR-AGT-4 | **Verifier agent** validates groundedness and policy compliance; can request revision (bounded loop) | M |
| FR-AGT-5 | **HR Operations agent** executes tool calls (leave, letters, onboarding) | M |
| FR-AGT-6 | **Escalation agent** creates an HR ticket with full conversation context | S |
| FR-AGT-7 | Workflow state is explicit and replayable (graph with checkpoints) | M |
| FR-AGT-8 | Maximum step, retry and cost budget per request | M |
| FR-AGT-9 | Human-in-the-loop approval for sensitive actions (e.g., leave approval, letters) | M |

### 5.5 HR Operations
| ID | Requirement | Pri |
|---|---|---|
| FR-HR-1 | Check leave balance and leave policy for the authenticated user | M |
| FR-HR-2 | Submit a leave request; route to manager for approval | M |
| FR-HR-3 | Generate employment/experience letter drafts from templates; HR approves before release | S |
| FR-HR-4 | Onboarding assistant: checklist, required documents, first-week FAQs | S |
| FR-HR-5 | Benefits and holiday calendar queries | S |
| FR-HR-6 | Create and track HR tickets | S |
| FR-HR-7 | HR connector abstraction with a mock HRIS in v1 | M |
| FR-HR-8 | Actions are idempotent and fully audit-logged | M |

### 5.6 Guardrails
| ID | Requirement | Pri |
|---|---|---|
| FR-GRD-1 | Input: prompt-injection / jailbreak detection | M |
| FR-GRD-2 | Input and output: PII detection and redaction (SSN-like IDs, bank, phone, email) with configurable rules | M |
| FR-GRD-3 | Topic policy: refuse legal advice, medical advice, and unrelated requests politely | M |
| FR-GRD-4 | RBAC: users only retrieve documents and perform actions allowed for their role | M |
| FR-GRD-5 | Output: toxicity and tone check; no disclosure of confidential or other employees' data | M |
| FR-GRD-6 | Tool guardrails: action allow-list, argument validation, spend/step limits | M |
| FR-GRD-7 | Guardrail decisions logged with reason and shown to admins | S |
| FR-GRD-8 | Rate limiting and abuse detection per user | S |

### 5.7 Observability and Audit
| ID | Requirement | Pri |
|---|---|---|
| FR-OBS-1 | End-to-end trace per request, spanning retrieval, each agent, each LLM call and each tool call | M |
| FR-OBS-2 | Track latency, token usage and cost per request, agent and user group | M |
| FR-OBS-3 | Track quality metrics: groundedness, citation coverage, abstention rate, escalation rate | M |
| FR-OBS-4 | Track guardrail triggers (injection, PII, RBAC denials) | M |
| FR-OBS-5 | Immutable audit log of HR actions and approvals | M |
| FR-OBS-6 | Offline evaluation suite (golden Q&A set) runnable in CI; regression thresholds | S |
| FR-OBS-7 | Alerts for error spikes, cost anomalies and groundedness drops | C |
| FR-OBS-8 | Admin dashboard in the React app with trends and drill-down to traces | S |

### 5.8 User Interface (React)
| ID | Requirement | Pri |
|---|---|---|
| FR-UI-1 | Chat interface with streaming responses | M |
| FR-UI-2 | Clickable citations that open the source passage with highlighting | M |
| FR-UI-3 | Visible agent-activity panel (steps taken) for transparency | S |
| FR-UI-4 | Approval inbox for managers and HR | M |
| FR-UI-5 | Admin console: documents, versions, ingestion status, guardrail settings | M |
| FR-UI-6 | Metrics and evaluation dashboard | S |
| FR-UI-7 | Feedback buttons and "escalate to HR" action | S |
| FR-UI-8 | Responsive layout and accessible (WCAG AA target) | S |

### 5.9 Authentication and Authorization
| ID | Requirement | Pri |
|---|---|---|
| FR-AUTH-1 | Login via JWT (OIDC-ready); mock identity provider in v1 | M |
| FR-AUTH-2 | Roles: Employee, Manager, HR, Compliance, Admin | M |
| FR-AUTH-3 | Role claims propagate to retrieval filters and tool permissions | M |

## 6. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Performance | p95 time-to-first-token < 2 s; p95 full answer < 10 s for Q&A |
| NFR-2 | Scalability | Support 100 concurrent users and 10k documents/chunks as the v1 target; stateless API |
| NFR-3 | Accuracy | Groundedness >= 95% and citation precision >= 90% on the golden set |
| NFR-4 | Reliability | Graceful degradation if LLM or reranker fails; timeouts and retries with backoff |
| NFR-5 | Security | Secrets in env/secret manager; TLS; encrypted data at rest; least privilege |
| NFR-6 | Privacy | PII never sent to the LLM unredacted unless explicitly permitted; configurable data retention |
| NFR-7 | Auditability | All decisions reproducible from trace + stored context |
| NFR-8 | Maintainability | Typed Python (pydantic), modular agents, >= 80% unit-test coverage on core logic |
| NFR-9 | Portability | Entire stack runnable via Docker Compose; LLM provider behind an interface |
| NFR-10 | Cost | Per-request cost budget and model tiering (small model for routing/verification checks) |
| NFR-11 | Compliance | Designed to support GDPR-style data subject requests (delete user chat history) |

## 7. Architecture Overview (High Level)

```
React UI  --->  FastAPI (auth, guardrails, API)
                    |
              LangGraph Orchestrator
   +--------+---------+----------+-----------+
 Router  Retriever  Answerer  Verifier   HR-Ops/Escalation
              |                              |
           Qdrant                      HR connector (mock HRIS)
                    |
      Telemetry (OpenTelemetry -> Langfuse/Phoenix), Postgres/SQLite (audit, chat, tickets)
```

Request flow (policy question):
1. Input guardrails (injection, PII, topic) -> 2. Router -> 3. Retriever (RBAC-filtered hybrid search + rerank) ->
4. Answerer (cited draft) -> 5. Verifier (claim-level groundedness; loop max N) ->
6. Output guardrails -> 7. Stream response + persist trace and audit.

Request flow (HR operation): Router -> HR-Ops agent -> tool call validation -> approval gate (if required) -> execution -> audited confirmation.

## 8. Data Requirements

| Entity | Key fields |
|---|---|
| Document | id, title, type, department, version, effective_date, status, allowed_roles, source_uri |
| Chunk (Qdrant payload) | doc_id, version, section, page, text, allowed_roles, dense/sparse vectors |
| User | id, name, role, department, manager_id |
| LeaveRequest | id, user_id, type, dates, status, approver, audit refs |
| Ticket | id, user_id, summary, context, status |
| AuditEvent | id, actor, action, params hash, outcome, trace_id, timestamp |
| ChatSession / Message | session_id, user_id, messages, citations, feedback |
| EvalCase | question, expected facts, expected sources, role |

Sample corpus for v1: synthetic HR handbook, leave policy, code of conduct, IT acceptable use, data
privacy policy, travel and expense policy, plus onboarding guide. No real employee data.

## 9. Key Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Hallucinated policy answer | Wrong guidance, compliance exposure | Citation-mandatory design, verifier agent, abstention, golden-set regression tests |
| Prompt injection via uploaded docs | Data leak or action hijack | Ingestion scanning, treat retrieved text as data, tool allow-lists, output checks |
| PII / confidential data leakage | Privacy breach | RBAC filters at retrieval, PII redaction, per-user data scoping |
| Outdated policy served | Incorrect answer | Versioning, effective dates, superseded filtering, freshness display |
| Runaway agent loops / cost | Cost and latency | Step/retry/cost budgets, model tiering |
| Over-trust in automation for HR actions | Wrong approvals | Human approval gates, idempotent audited actions |
| LLM provider outage or drift | Degraded service | Provider abstraction, timeouts, fallback, evals in CI |

## 10. Assumptions and Constraints
- A: Policy documents are provided in digital text-based formats; scanned OCR is out of v1 scope.
- A: English only.
- A: HRIS integration is mocked in v1; real integration is a later phase.
- C: Qdrant is the sole vector store; FastAPI backend; React frontend.
- C: Developed and demoed locally via Docker Compose.

## 11. Success Metrics

| Metric | Target |
|---|---|
| Groundedness (golden set) | >= 95% |
| Citation precision | >= 90% |
| Correct abstention on out-of-scope / unanswerable set | >= 90% |
| Prompt-injection test pass rate | >= 95% |
| HR operation task success (scripted scenarios) | >= 90% |
| p95 latency (Q&A) | < 10 s |
| Avg cost per Q&A | Tracked, with a budget set at kickoff |

## 12. Delivery Phases

| Phase | Deliverables |
|---|---|
| 1. Foundation | Repo, Docker Compose (Qdrant, API, UI), auth stub, ingestion pipeline, basic RAG with citations |
| 2. Trustworthy Q&A | Hybrid search, reranking, verifier agent, abstention, versioning, golden-set evals |
| 3. Multi-Agent and HR Ops | LangGraph orchestration, router, HR-Ops tools, approval inbox, escalation |
| 4. Guardrails | Injection/PII/topic/RBAC guardrails, tool policies, red-team test suite |
| 5. Observability | Traces, cost/quality metrics, audit log, admin dashboard, CI eval gate |
| 6. Hardening | Load test, security review, docs, demo scenarios |

## 13. Open Questions
1. Which LLM tiers (e.g., small model for routing, larger for answering) and what per-request budget?
2. Langfuse vs Arize Phoenix for tracing?
3. Which guardrail library: Guardrails AI, NeMo Guardrails, or custom rules plus a small classifier?
4. Do approvals need email/Slack notification in v1, or in-app only?
5. Data retention period for chat history and traces?
6. Should the verifier run synchronously (safer, slower) or after streaming with a retraction mechanism?

## 14. Traceability to Learning Objectives

| Concept | Where it lives |
|---|---|
| RAG | 5.1, 5.2 |
| Hallucination prevention | 5.3, verifier agent in 5.4 |
| Multi-agent orchestration | 5.4, 5.5 |
| Guardrails | 5.6, 5.9 |
| Observability tracking | 5.7, NFR-7 |
