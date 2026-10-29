# Enterprise Policy, Compliance & HR Operations Copilot

A grounded, auditable AI assistant that answers employee questions about company policy
(HR, IT, security, legal, compliance) and handles routine HR operations requests
(leave, onboarding, benefits, letters) with citations, guardrails and full observability.

| Concern | Implementation |
|---|---|
| RAG | Qdrant hybrid search (dense + sparse), reranking, metadata filters |
| Hallucination prevention | Mandatory citations, groundedness verification, abstain-when-unsure |
| Multi-agent orchestration | LangGraph: router, retriever, answerer, verifier, HR-ops agents |
| Guardrails | PII redaction, prompt-injection defense, RBAC, topic and action policy |
| Observability | Traces, cost/latency, groundedness metrics, audit log (Langfuse/Phoenix + OpenTelemetry) |

## Stack
- **Backend:** Python, FastAPI
- **Vector DB:** Qdrant
- **Frontend:** React (Vite)
- **Orchestration:** LangGraph, Claude API

## Layout
```
backend/    FastAPI service, agents, RAG pipeline
frontend/   React chat UI, trace panel, admin dashboard
docs/       Requirements and design documents
```

## Documentation
- [Requirements Analysis](docs/requirements-analysis.md)

## Status
Planning. Requirements drafted; implementation not started.
