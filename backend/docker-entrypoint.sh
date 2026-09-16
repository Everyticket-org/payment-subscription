#!/bin/sh
# Runs Alembic migrations once, only for the backend (uvicorn) container -
# not for the worker/beat containers, which share this same image via
# docker-compose.yml's `command:` override. Running migrations from
# every container that shares the image would race against itself on a
# fresh deploy; running it from exactly one entrypoint is deterministic
# and alembic_version's own locking makes it safe to re-run on restart.
set -e

if [ "$1" = "uvicorn" ]; then
    echo "Running database migrations (alembic upgrade head)..."
    alembic upgrade head
fi

exec "$@"
