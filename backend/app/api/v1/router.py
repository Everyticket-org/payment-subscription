"""Aggregates every /api/v1/* sub-router (spec section 61)."""
from fastapi import APIRouter

from app.api.v1 import admin, customer, integration, payment, public, webhooks

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(public.router)
api_v1_router.include_router(payment.router)
api_v1_router.include_router(admin.router)
api_v1_router.include_router(customer.router)
api_v1_router.include_router(webhooks.router)
api_v1_router.include_router(integration.router)
