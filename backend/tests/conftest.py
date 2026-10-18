import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_gepa.db"
os.environ["SEED_DEMO"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, email="doctor@gepa.local", password="doctor123"):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def doctor(client):
    return login(client)


@pytest.fixture(scope="session")
def nurse(client):
    return login(client, "nurse@gepa.local", "nurse1234")


@pytest.fixture(scope="session")
def analyst(client):
    return login(client, "analyst@gepa.local", "analyst123")
