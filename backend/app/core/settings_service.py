"""Generic key/value accessors over the SystemSetting table (spec section
57). Kept deliberately generic (not invoice/tax-specific) so the future
System/Gateway/Integration/Notification/Security configuration admin
screens (spec section 51 - not yet built, see docs/implementation-status.md)
can reuse the same read/write primitives instead of each inventing its own
settings-storage pattern.

Not cached (unlike app.core.config.get_settings(), which is a process-wide
@lru_cache singleton for infra-level env config) - these are business
config values an admin can change at runtime and expects to take effect on
the very next request, so every call reads straight from the DB.
"""
from sqlalchemy.orm import Session

from app.core.models import SystemSetting


def get_setting(db: Session, *, key: str) -> dict | None:
    """Returns the raw JSON value dict for `key`, or None if unset."""
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return row.value if row is not None else None


def set_setting(db: Session, *, key: str, value: dict, description: str | None = None) -> SystemSetting:
    """Upserts `key` -> `value`. Caller is responsible for committing."""
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row is None:
        row = SystemSetting(key=key, value=value, description=description)
        db.add(row)
    else:
        row.value = value
        if description is not None:
            row.description = description
        db.add(row)
    db.flush()
    return row
