import os

import psycopg
import pytest

ADMIN = os.environ.get("DATABASE_URL", "postgresql://app:app-dev-only@127.0.0.1:55240/app")
TEST_DB = ADMIN.rsplit("/", 1)[1] + "_test"                     # app -> app_test; one test database per project database
os.environ["DATABASE_URL"] = ADMIN.rsplit("/", 1)[0] + "/" + TEST_DB


@pytest.fixture(scope="session")
def seeded():
    """A fresh database with the tenants and their tokens; the domain data arrives through the load job in the tests."""
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {TEST_DB}")
    from core import db
    from wh import seed
    out = seed.main()
    yield out
    db.close()


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient

    from wh.api import app
    return TestClient(app)


def bearer(tenant, role):
    return {"Authorization": f"Bearer {tenant}-{role}-demo"}
