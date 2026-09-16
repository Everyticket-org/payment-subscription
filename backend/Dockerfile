# Multi-stage build: compile deps in a throwaway "builder" stage, then
# copy only the resulting virtualenv + app code into a slim runtime
# image. Keeps the final image smaller and free of compiler toolchains,
# and runs as a non-root user - both are dockerbench/CIS-style baseline
# hardening for anything deployed to a real server.
#
# This image is shared by the backend API, the Celery worker, and the
# Celery beat scheduler - docker-compose.yml overrides CMD for the
# latter two. All three need the exact same code + dependencies, so one
# image built once (not three separate builds) is both correct and
# faster to build/deploy.

FROM python:3.12-slim AS builder

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# build-essential covers the rare case a dependency has no prebuilt wheel
# for this platform (e.g. a future arm64 deploy). Every current
# dependency (PyMySQL, bcrypt, cryptography via python-jose) ships
# manylinux/abi3 wheels for linux/amd64, so this normally does no actual
# compiling - it's a safety net, not a requirement. No libpq-dev: that
# was Postgres-specific and stale since the 2026-09-13 MySQL switch (see
# app/core/config.py's DATABASE_URL comment) - PyMySQL is pure Python.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root: if the app is ever compromised (a dependency CVE, a bad
# upload, etc.), the process shouldn't have root inside its own
# container. UID 10001 is arbitrary but fixed, so bind-mounted volume
# ownership (var/, migrations output) stays predictable across rebuilds.
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .
RUN chmod +x docker-entrypoint.sh

# var/ holds generated invoice PDFs (INVOICE_PDF_STORAGE_DIR) and, for
# the beat container, the celerybeat-schedule file - both written at
# runtime, so the directory must exist and be writable by the app user
# before the app ever starts.
RUN mkdir -p var && chown app:app var

USER app

EXPOSE 8002

# Reuses the app's own /health endpoint (app/main.py) rather than a
# separate probe - it already checks DB connectivity, so "healthy" here
# means "can actually serve requests", not just "process is running".
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8002/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
