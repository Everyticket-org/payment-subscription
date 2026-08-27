"""Integration-facing API (spec sections 30-33, 61: /api/v1/integration/) -
e.g. Everyticket SSO handoff validation. Not yet implemented (see
docs/implementation-status.md)."""
from fastapi import APIRouter

router = APIRouter(prefix="/integration", tags=["integration"])
