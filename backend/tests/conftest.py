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
import os

# Must be set before any app module is imported: app.core.config.get_settings()
# is @lru_cache'd and several modules (e.g. app.auth.otp_service,
# app.auth.service) call it at import time and hold the result in a
# module-level `settings` variable. Setting these here - rather than relying
# on whoever invokes pytest to have exported them - is what makes this test
# suite "testable without any real external dependencies" (see module
# docstring below): the bypass flags must be on for the BYPASS-code tests
# and helpers (e.g. tests/test_subscription_lifecycle.py's _customer_token),
# and TEST_MODE must be on so /identify surfaces debug_otp_code (spec
# section 11 - no real SMS/email channel exists yet, see
# app.auth.otp_service's module docstring). setdefault() so a real CI
# environment can still override these explicitly if it ever needs to.
os.environ.setdefault("TEST_MODE", "true")
os.environ.setdefault("ALLOW_OTP_BYPASS", "true")
os.environ.setdefault("ALLOW_ADMIN_MFA_BYPASS", "true")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("JWT_SECRET", "pytest-only-secret-never-used-outside-tests")

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
