"""Pydantic schemas for plans (spec sections 14, 15, 17)."""
from pydantic import BaseModel, ConfigDict


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
