"""Pydantic schemas for plans (spec sections 14, 15, 16, 51)."""
from pydantic import BaseModel, ConfigDict, Field


class PlanFeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    feature_key: str
    feature_label: str
    feature_value: str | None = None
    display_order: int


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    plan_code: str
    name: str
    description: str | None = None
    price: float
    currency: str
    billing_interval: str
    billing_frequency: int
    display_order: int
    features: list[PlanFeatureOut] = []

    @property
    def public_url(self) -> str:
        return f"/subscribe/{self.plan_code.lower()}"


# --- Admin-only schemas below (spec section 51 "Plans" / "Plan Features" /
# "Plan Transitions" admin modules). Unlike PlanOut/PlanFeatureOut above
# (public catalog view), these expose internal ids and the `active` flag,
# and are used for both list/detail responses and create/update bodies. ---


class PlanFeatureAdminOut(PlanFeatureOut):
    id: int


class PlanFeatureCreate(BaseModel):
    feature_key: str = Field(min_length=1, max_length=100)
    feature_label: str = Field(min_length=1, max_length=255)
    feature_value: str | None = Field(default=None, max_length=500)
    display_order: int = 0


class PlanFeatureUpdate(BaseModel):
    feature_label: str | None = Field(default=None, min_length=1, max_length=255)
    feature_value: str | None = Field(default=None, max_length=500)
    display_order: int | None = None


class PlanAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    plan_code: str
    name: str
    description: str | None = None
    price: float
    currency: str
    billing_interval: str
    billing_frequency: int
    active: bool
    display_order: int
    features: list[PlanFeatureAdminOut] = []


class PlanCreate(BaseModel):
    plan_code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=255)
    # Rich-text HTML from the admin description editor (bold/italic/bullet
    # +numbered lists) - sanitized server-side to a strict tag allowlist
    # before storage, see app.plans.sanitize.sanitize_description(). The
    # generous cap is just an abuse guard, not a real content limit.
    description: str | None = Field(default=None, max_length=20000)
    price: float = Field(gt=0)
    currency: str = Field(default="INR", max_length=10)
    billing_interval: str = Field(default="month", pattern="^(month|year)$")
    billing_frequency: int = Field(default=1, ge=1)
    display_order: int = 0


class PlanUpdate(BaseModel):
    """All fields optional - only supplied fields are changed. `plan_code`
    is immutable once created (it's part of the public /subscribe/{code}
    URL and may already be referenced by live subscriptions/payments)."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    price: float | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, max_length=10)
    billing_interval: str | None = Field(default=None, pattern="^(month|year)$")
    billing_frequency: int | None = Field(default=None, ge=1)
    active: bool | None = None
    display_order: int | None = None


class PlanReorderRequest(BaseModel):
    """Bulk reorder (spec section 51's Plans admin module): the full list
    of this application's plan codes in the desired display order -
    display_order is then set to each code's index in the list. One audit
    log entry for the whole reorder, rather than N individual PLAN_UPDATED
    entries from N separate PUTs."""
    plan_codes: list[str] = Field(min_length=1)


class PlanTransitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    from_plan_code: str
    to_plan_code: str
    transition_type: str


class PlanTransitionCreate(BaseModel):
    from_plan_code: str
    to_plan_code: str
    transition_type: str = Field(pattern="^(UPGRADE|DOWNGRADE)$")
