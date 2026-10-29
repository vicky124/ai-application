from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.auth import User, authenticate, current_user, require_roles
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


@app.post("/api/documents")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_id: str = Form(...),
    department: str = Form("General"),
    version: str = Form("1.0"),
    allowed_roles: str = Form("all"),
    user: User = Depends(DocAdmin),
    c: Container = Depends(get_container),
):
    meta = DocumentMeta(doc_id, title, department, version, "active", [r.strip() for r in allowed_roles.split(",")])
    try:
        n = c.ingestion.ingest_bytes(file.filename or "upload.txt", await file.read(), meta)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"doc_id": doc_id, "chunks": n}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, user: User = Depends(DocAdmin), c: Container = Depends(get_container)):
    c.store.delete(doc_id)
    return {"deleted": doc_id}


@app.get("/health")
def health():
    return {"status": "ok"}
