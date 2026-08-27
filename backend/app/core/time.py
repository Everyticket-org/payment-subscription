"""
Timezone-safety helper.

SQLAlchemy's DateTime(timezone=True) round-trips correctly on PostgreSQL
(the production and cloud-test database) but SQLite - used only for the
pytest suite's in-memory database, see tests/conftest.py - has no native
timezone-aware datetime type and hands back a naive datetime regardless
of what was stored. Comparing that naive value directly against
datetime.now(timezone.utc) raises TypeError: can't compare offset-naive
and offset-aware datetimes.

Rather than special-case the test database, every comparison against a
datetime that came back from the ORM should go through ensure_aware()
first. It is a no-op on Postgres (already aware) and makes SQLite
consistent by assuming naive values are UTC, which holds here because
every datetime this app writes is produced by datetime.now(timezone.utc).
"""
from datetime import datetime, timezone


def ensure_aware(value: datetime) -> datetime:
    """Return value with UTC tzinfo attached if it came back naive."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
