"""Invoice GST/tax configuration (spec sections 45, 51, 81).

Stored as a single app.core.models.SystemSetting row (key
"invoice_tax_config") rather than a new dedicated table - it's one small
admin-editable business rule, exactly the case that table exists for
(see app/core/models.py's docstring).

Default is 0% / no seller GSTIN configured, i.e. tax calculation stays
OFF until an admin deliberately turns it on - the same "make it
configurable, default DISABLED" pattern the spec already uses for
proration/refunds (section 42). This also means every invoice generated
before an admin configures a rate keeps behaving exactly as it did before
this module existed (tax_amount == 0), so nothing retroactively changes
for already-issued invoices.
"""
from sqlalchemy.orm import Session

from app.core.settings_service import get_setting, set_setting
from app.invoices.schemas import TaxConfigOut, TaxConfigUpdate

_SETTING_KEY = "invoice_tax_config"


def get_tax_config(db: Session) -> TaxConfigOut:
    value = get_setting(db, key=_SETTING_KEY)
    if value is None:
        return TaxConfigOut(gst_rate_percent=0, seller_gstin=None, tax_label="GST")
    return TaxConfigOut(**value)


def set_tax_config(db: Session, *, update: TaxConfigUpdate) -> TaxConfigOut:
    set_setting(
        db,
        key=_SETTING_KEY,
        value=update.model_dump(),
        description="Invoice GST/tax rate + seller GSTIN used when generating invoices (spec section 45).",
    )
    db.commit()
    return get_tax_config(db)
