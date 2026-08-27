"""Admin API (spec sections 51-54, 61: /api/v1/admin/). Not yet
implemented in this pass - admin auth (JWT + MFA), plan/form management,
customer/subscription/payment/invoice views, webhook/email/audit logs, and
the Testing module all land here in a follow-up (see
docs/implementation-status.md). Router is wired up now so the URL
namespace and module boundary exist from the start."""
from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])
