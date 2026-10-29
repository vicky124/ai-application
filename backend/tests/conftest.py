import os
import tempfile

# Must be set before app modules import settings: offline embeddings, throwaway Qdrant storage.
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["QDRANT_PATH"] = tempfile.mkdtemp(prefix="qdrant_test_")
os.environ["MIN_RETRIEVAL_SCORE"] = "0.15"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def token(client, user, pw):
    return client.post("/auth/login", json={"username": user, "password": pw}).json()["access_token"]


@pytest.fixture(scope="session")
def alice(client):
    return {"Authorization": f"Bearer {token(client, 'alice', 'alice123')}"}


@pytest.fixture(scope="session")
def hannah(client):
    return {"Authorization": f"Bearer {token(client, 'hannah', 'hannah123')}"}
