"""
Shared pytest fixtures.

Tests run against an in-memory SQLite database rather than Postgres, so
the suite is fast and needs no external services (spec section 73: the
whole application must be testable without any real external
dependencies). This deliberately does NOT exercise the Postgres-only
partial unique index (one-active-subscription-per-customer) - that
constraint is verified separately, against real Postgres, as part of
generating/applying the Alembic migration (see
docs/implementation-status.md for how that was verified). These tests
verify application-level enforcement of the same rule
(subscriptions.service.create_pending_subscription raising
CustomerAlreadySubscribed), which runs regardless of database backend.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core import models_registry  # noqa: F401 - populate metadata
from app.core.seed import seed
from app.main import app

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(_engine)
    yield
    Base.metadata.drop_all(_engine)


@pytest.fixture()
def db_session():
    session = _TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_data():
    """Truncate every table before each test so tests are independent,
    without paying for a full schema rebuild per test."""
    with _engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture()
def seeded_db(db_session):
    seed(db_session)
    return db_session


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
