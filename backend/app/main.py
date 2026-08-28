"""
FastAPI application entrypoint (spec sections 61, 63, 83).

Structured exceptions (app.core.exceptions.AppError subclasses) are caught
here and turned into a consistent {"error_code": ..., "message": ...} JSON
body - no stack trace ever reaches the client. Unhandled exceptions are
logged and returned as a generic 500 for the same reason.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core import models_registry  # noqa: F401 - must import before any ORM mapper is used,
# so every model (including ones only referenced via string relationship()
# targets, e.g. Application.form_fields -> RegistrationFormField) is
# registered on Base.metadata before SQLAlchemy configures its mappers.
from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import AppError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("subscription")

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="Everyticket Subscription Management Platform API (Phase 1, in progress)",
)

# The React frontend (spec section 77) runs on a different origin in dev
# (`npm run dev` on :5173 vs. the backend on :8000), so every browser
# request needs this or it never reaches app code at all. allow_credentials
# stays False - auth is a Bearer token in the Authorization header, not a
# cookie, so no cross-origin credential is ever sent.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_v1_router)


@app.exception_handler(AppError)
def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error_code": exc.error_code, "message": exc.message},
    )


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception processing %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
    )


@app.get("/health", tags=["ops"])
def health() -> dict:
    """Liveness - process is up. Does not check dependencies (see /ready)."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready() -> JSONResponse:
    """Readiness - verifies the database is reachable (spec section 83).
    Redis/Celery connectivity checks are added once background jobs are
    wired up."""
    checks = {"database": "unknown"}
    healthy = True

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover - defensive
        checks["database"] = f"error: {exc}"
        healthy = False
    finally:
        db.close()

    status_code = 200 if healthy else 503
    return JSONResponse(status_code=status_code, content={"status": "ok" if healthy else "degraded", "checks": checks})
