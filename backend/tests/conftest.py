"""
Shared pytest fixtures.

Tests run against an in-memory SQLite database rather than the real
production database (MySQL, as of the 2026-09-13 "change database to
mysql" follow-up), so the suite is fast and needs no external services
(spec section 73: the whole application must be testable without any
real external dependencies).

The one-active-subscription-per-customer / one-trial-per-lifetime rules
(app.subscriptions.models.Subscription's two unique indexes) are backed
by generated columns (active_slot/trial_slot) specifically so they work
identically across SQLite, MySQL, and Postgres - see that model's module
docstring for why. That means these tests DO exercise the real DB-level
constraint (SQLite creates the same GENERATED ALWAYS AS ... STORED
columns + unique indexes), not just the application-level pre-check
(subscriptions.service.create_pending_subscription raising
CustomerAlreadySubscribed) - both layers are covered here. The DB-level
constraint was additionally verified directly against a real MySQL 8.0
instance as part of migrating to it (see docs/implementation-status.md).
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
# Force-blank (not setdefault - a developer's real backend/.env may set these
# to a real bootstrap password) so app.core.seed.seed() always falls back to
# its hardcoded dev-default admin login (admin@example.com / ChangeMe123!),
# matching what tests/test_admin_api.py's _admin_token() helper hardcodes.
# Without this, a developer's local ADMIN_BOOTSTRAP_EMAIL/PASSWORD (kept in
# backend/.env for their own real dev database) leaks into the test suite's
# in-memory DB and every admin-authenticated test fails with 401.
os.environ["ADMIN_BOOTSTRAP_EMAIL"] = ""
os.environ["ADMIN_BOOTSTRAP_PASSWORD"] = ""

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
