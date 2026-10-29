import json
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import ROLES, User, authenticate, current_user, require_roles
from app.config import settings
from app.container import Container, get_container
from app.domain import DocumentMeta


@asynccontextmanager
async def lifespan(app: FastAPI):
    c = get_container()
    if settings.autoload_samples and not c.store.list_documents():
        c.ingestion.ingest_directory(settings.sample_docs_dir)
    yield


app = FastAPI(title="Policy & HR Copilot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)

DocAdmin = require_roles("admin", "hr", "compliance")


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    question: str
    model_id: str | None = None


@app.post("/auth/login")
def login(body: LoginRequest):
    token = authenticate(body.username, body.password)
    if not token:
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": token}


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/models")
def list_models(user: User = Depends(current_user), c: Container = Depends(get_container)):
    return {
        "default": c.models.default_id,
        "models": [{"id": m.id, "label": m.label, "provider": m.provider} for m in c.models.specs()],
    }


@app.post("/api/chat")
def chat(body: ChatRequest, user: User = Depends(current_user), c: Container = Depends(get_container)):
    try:
        c.models.get(body.model_id)
    except KeyError:
        raise HTTPException(400, f"Unknown model '{body.model_id}'")
    except Exception as e:  # provider could not be constructed
        raise HTTPException(503, f"Model unavailable: {e}")
    try:
        state = c.agent.run(body.question, user.role, body.model_id)
    except Exception as e:  # e.g. Ollama not running or model not pulled
        raise HTTPException(
            503,
            f"Model '{body.model_id or c.models.default_id}' is unavailable ({type(e).__name__}). "
            "If it is an Ollama model, check that Ollama is running and the model is pulled, or pick another model.",
        )
    v = state.get("verification")
    return {
        "answer": state["answer"],
        "abstained": state["abstained"],
        "abstain_reason": state.get("abstain_reason"),
        "model_id": body.model_id or c.models.default_id,
        "sources": [s.__dict__ for s in state.get("sources", [])] if not state["abstained"] else [],
        "verification": {"passed": v.passed, "reason": v.reason, "coverage": v.coverage} if v else None,
        "trace": state["trace"],
    }


@app.get("/api/documents")
def documents(user: User = Depends(DocAdmin), c: Container = Depends(get_container)):
    return c.store.list_documents()


DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,60}$")
VALID_STATUS = ("active", "inactive", "draft")


def build_meta(title: str, doc_id: str, department: str, version: str, allowed_roles: str, status: str) -> DocumentMeta:
    if not DOC_ID_RE.match(doc_id):
        raise HTTPException(400, "doc_id must be 2-61 chars: lowercase letters, digits, '-' or '_'")
    if status not in VALID_STATUS:
        raise HTTPException(400, f"status must be one of {VALID_STATUS}")
    roles = [r.strip() for r in allowed_roles.split(",") if r.strip()]
    bad = [r for r in roles if r != "all" and r not in ROLES]
    if not roles or bad:
        raise HTTPException(400, f"allowed_roles must be 'all' or a list of {list(ROLES)}")
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
    user: User = Depends(DocAdmin),
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
    user: User = Depends(DocAdmin),
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
def delete_document(doc_id: str, user: User = Depends(DocAdmin), c: Container = Depends(get_container)):
    c.store.delete(doc_id)
    return {"deleted": doc_id}


@app.get("/health")
def health():
    return {"status": "ok"}
