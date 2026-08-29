"""
Shared helpers for the admin API's list/detail endpoints (spec section 51).

Kept in its own module (rather than duplicated per admin_*.py file) since
every "Customers"/"Subscriptions"/"Payments"/"Invoices"/"Webhook Logs"/
"Audit Logs" list endpoint needs the same limit/offset pagination shape.
"""
from typing import Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Query

T = TypeVar("T")


class PageOut(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def paginate(query: Query, *, limit: int, offset: int) -> tuple[list, int]:
    """Runs a COUNT and a LIMIT/OFFSET SELECT against the same filtered
    query. Two queries rather than a window function - simpler, and list
    endpoints here are admin-facing (low QPS), not hot customer paths."""
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return items, total
