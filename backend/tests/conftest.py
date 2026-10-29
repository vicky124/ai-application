import os
import tempfile
from pathlib import Path

# Must be set before app modules import settings: offline embeddings, throwaway Qdrant storage, test identity DB.
# Set TEST_DATABASE_URL to a Postgres URL (e.g. postgresql+psycopg://policy:policy@localhost:5432/policy_test)
# to run the suite against Postgres; otherwise a throwaway SQLite file is used.
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["QDRANT_PATH"] = tempfile.mkdtemp(prefix="qdrant_test_")
os.environ["MIN_RETRIEVAL_SCORE"] = "0.15"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{Path(tempfile.mkdtemp(prefix='auth_test_')) / 'auth.db'}"
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123"
os.environ["SEED_DEMO_USERS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def token(client, user, pw):
    return client.post("/auth/login", json={"username": user, "password": pw}).json()["access_token"]


def bearer(client, user, pw):
    return {"Authorization": f"Bearer {token(client, user, pw)}"}


@pytest.fixture(scope="session")
def alice(client):
    return bearer(client, "alice", "alice123")


@pytest.fixture(scope="session")
def hannah(client):
    return bearer(client, "hannah", "hannah123")


@pytest.fixture(scope="session")
def admin(client):
    return bearer(client, "root", "root123")


@pytest.fixture(scope="session")
def carl(client):
    return bearer(client, "carl", "carl123")
