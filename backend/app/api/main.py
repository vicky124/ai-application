import json
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from fastapi.responses import JSONResponse

from app.auth import ROLE_NAMES, CurrentUser, require_permission
from app.auth.deps import get_hasher
from app.auth.errors import ServiceError
from app.auth.router import api_router, auth_router
from app.config import settings
from app.container import Container, get_container
from app.db.bootstrap import init_database
from app.db.session import get_database
from app.domain import DocumentMeta
from app.providers.generators import ModelUnavailable


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database(get_database(), get_hasher())
    c = get_container()
    if settings.autoload_samples and not c.store.list_documents():
        c.ingestion.ingest_directory(settings.sample_docs_dir)
    yield


app = FastAPI(title="Policy & HR Copilot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)
app.include_router(auth_router)
app.include_router(api_router)


@app.exception_handler(ServiceError)
async def service_error_handler(_, exc: ServiceError):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)


DocAdmin = require_permission("documents:manage")
ChatUser = require_permission("chat:use")


class ChatRequest(BaseModel):
    question: str
    model_id: str | None = None


@app.get("/api/models")
def list_models(user: CurrentUser = Depends(ChatUser), c: Container = Depends(get_container)):
    return {
        "default": c.models.default_id,
        "models": [c.models.describe(m) for m in c.models.specs()],
    }


@app.post("/api/chat")
def chat(body: ChatRequest, user: CurrentUser = Depends(ChatUser), c: Container = Depends(get_container)):
    model_id = body.model_id or c.models.default_id
    try:
        c.models.get(body.model_id)
    except KeyError:
        raise HTTPException(400, f"Unknown model '{body.model_id}'")
    except ModelUnavailable as e:  # e.g. missing API key; the reason is written by us, never provider output
        raise HTTPException(503, f"Model '{model_id}' is unavailable: {e}")
    except Exception as e:  # provider could not be constructed
        raise HTTPException(503, f"Model '{model_id}' could not be loaded ({type(e).__name__}).")
    try:
        state = c.agent.run(body.question, user.role, body.model_id)
    except Exception as e:  # provider unreachable, quota exceeded, model not pulled, ...
        raise HTTPException(
            503,
            f"Model '{model_id}' failed ({type(e).__name__}). Check that its provider is reachable and configured "
            "(Ollama running and the model pulled, or the Gemini key valid with quota), or pick another model.",
        )
    v = state.get("verification")
    return {
        "answer": state["answer"],
        "abstained": state["abstained"],
        "abstain_reason": state.get("abstain_reason"),
        "model_id": model_id,
        "model_local": next(c.models.describe(m)["local"] for m in c.models.specs() if m.id == model_id),
        "sources": [s.__dict__ for s in state.get("sources", [])] if not state["abstained"] else [],
        "verification": (
            {
                "passed": v.passed,
                "reason": v.reason,
                "coverage": v.coverage,
                "confidence": v.confidence,
                "claims": [
                    {"claim": c.claim, "cited": list(c.cited), "verdict": c.verdict, "strength": c.strength, "reason": c.reason}
                    for c in v.claims
                ],
            }
            if v
            else None
        ),
        "trace": state["trace"],
    }


@app.get("/api/documents")
def documents(user: CurrentUser = Depends(DocAdmin), c: Container = Depends(get_container)):
    return c.store.list_documents()


DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,60}$")
VALID_STATUS = ("active", "inactive", "draft")


def build_meta(title: str, doc_id: str, department: str, version: str, allowed_roles: str, status: str) -> DocumentMeta:
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(400, "doc_id must be 2-61 chars: lowercase letters, digits, '-' or '_'")
    if status not in VALID_STATUS:
        raise HTTPException(400, f"status must be one of {VALID_STATUS}")
    roles = [r.strip() for r in allowed_roles.split(",") if r.strip()]
    bad = [r for r in roles if r != "all" and r not in ROLE_NAMES]
    if not roles or bad:
        raise HTTPException(400, f"allowed_roles must be 'all' or a list of {list(ROLE_NAMES)}")
    return DocumentMeta(doc_id, title.strip() or doc_id, department, version, status, roles)


@app.post("/api/documents")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_id: str = Form(...),
    department: str = Form("General"),
    version: str = Form("1.0"),
    allowed_roles: str = Form("all"),
    status: str = Form("active"),
    user: CurrentUser = Depends(DocAdmin),
    c: Container = Depends(get_container),
):
    meta = build_meta(title, doc_id, department, version, allowed_roles, status)
    try:
        n = c.ingestion.ingest_bytes(file.filename or "upload.txt", await file.read(), meta)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"doc_id": doc_id, "chunks": n}


@app.post("/api/documents/ingest")
async def ingest_with_progress(
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_id: str = Form(...),
    department: str = Form("General"),
    version: str = Form("1.0"),
    allowed_roles: str = Form("all"),
    status: str = Form("active"),
    user: CurrentUser = Depends(DocAdmin),
    c: Container = Depends(get_container),
):
    """Runs the ingestion pipeline and streams one JSON event per line (NDJSON) as each stage finishes."""
    meta = build_meta(title, doc_id, department, version, allowed_roles, status)
    data = await file.read()
    filename = file.filename or "upload.txt"

    def events():
        for event in c.pipeline.run(filename, data, meta):
            yield json.dumps(event) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user: CurrentUser = Depends(DocAdmin), c: Container = Depends(get_container)):
    c.store.delete(doc_id)
    return {"deleted": doc_id}


@app.get("/health")
def health():
    return {"status": "ok"}
