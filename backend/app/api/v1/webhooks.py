"""Inbound webhook receivers (spec sections 30-37, 61: /api/v1/webhooks/).
Everyticket's response callbacks (e.g. provisioning result) land here once
the Everyticket integration adapter exists (see
docs/implementation-status.md)."""
from fastapi import APIRouter

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
