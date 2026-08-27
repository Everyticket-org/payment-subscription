"""
Customer identity resolution (spec sections 7, 9, 10).

LIMITATION (tracked in docs/implementation-status.md): this pass implements
only the safe "exact match" and "no match" cases -
  - email AND mobile both match an existing customer -> reuse that customer
  - otherwise -> create a new customer
The full duplicate-detection matrix (email-only match, mobile-only match,
OTP-gated identity reveal, SAME/HIGHER/LOWER/EXPIRED plan routing - spec
sections 9-11) is intentionally deferred; partial matches are NOT
auto-merged here (that would violate section 10), they simply fall through
to "create a new customer" for now, which is safe but not yet feature-complete.
"""
from sqlalchemy.orm import Session

from app.core.ids import new_customer_id
from app.customers.models import Customer


def find_exact_match(db: Session, *, email: str, mobile: str) -> Customer | None:
    return (
        db.query(Customer)
        .filter(Customer.email == email, Customer.mobile == mobile)
        .first()
    )


def create_customer(db: Session, *, email: str, mobile: str) -> Customer:
    customer = Customer(customer_id=new_customer_id(), email=email, mobile=mobile)
    db.add(customer)
    db.flush()
    return customer


def get_or_create_customer(db: Session, *, email: str, mobile: str) -> Customer:
    existing = find_exact_match(db, email=email, mobile=mobile)
    if existing is not None:
        return existing
    return create_customer(db, email=email, mobile=mobile)
