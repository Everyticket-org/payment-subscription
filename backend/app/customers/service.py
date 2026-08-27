"""
Customer identity resolution (spec sections 7, 9, 10).

find_match_status() implements the three safe cases from spec section 10:
  - "exact": email AND mobile both match one existing customer -> identify
    them (gated behind OTP verification by the caller, spec section 9).
  - "conflict": email matches one customer OR mobile matches one customer,
    but not both together (or they point at different customers) -> do
    NOT auto-merge, do NOT auto-create; the API layer returns a distinct
    response directing to manual support (spec section 10's explicit
    requirement).
  - "none": no match at all -> safe to create a new customer directly.
"""
from sqlalchemy.orm import Session

from app.core.ids import new_customer_id
from app.core.security import create_access_token
from app.customers.models import Customer


def find_match_status(db: Session, *, email: str, mobile: str) -> tuple[str, Customer | None]:
    exact = (
        db.query(Customer)
        .filter(Customer.email == email, Customer.mobile == mobile)
        .first()
    )
    if exact is not None:
        return "exact", exact

    email_match = db.query(Customer).filter(Customer.email == email).first()
    mobile_match = db.query(Customer).filter(Customer.mobile == mobile).first()
    if email_match is not None or mobile_match is not None:
        return "conflict", None

    return "none", None


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
    """Used only for the NO_EXISTING_CUSTOMER path (spec section 9) - callers
    must have already checked find_match_status() == 'none' (or gone
    through OTP identification for 'exact') before reaching here."""
    existing = find_exact_match(db, email=email, mobile=mobile)
    if existing is not None:
        return existing
    return create_customer(db, email=email, mobile=mobile)


def issue_customer_token(customer: Customer) -> str:
    """Short-lived bearer token issued after OTP verification (spec
    section 9-11), used by /subscribe (for repurchase/identified flows)
    and the customer portal endpoints. See app.auth.deps.get_current_customer_id."""
    return create_access_token(customer.customer_id, extra_claims={"token_kind": "customer"})
