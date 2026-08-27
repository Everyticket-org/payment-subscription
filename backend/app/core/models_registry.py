"""
Import every ORM model module so `Base.metadata` is fully populated before
Alembic autogenerate (or Base.metadata.create_all in tests) runs. Nothing
here is meant to be imported directly for its symbols - it's a side-effect
import aggregator only.
"""
from app.applications import models as _applications_models  # noqa: F401
from app.audit import models as _audit_models  # noqa: F401
from app.auth import models as _auth_models  # noqa: F401
from app.core import models as _core_models  # noqa: F401
from app.customers import models as _customers_models  # noqa: F401
from app.forms import models as _forms_models  # noqa: F401
from app.invoices import models as _invoices_models  # noqa: F401
from app.notifications import models as _notifications_models  # noqa: F401
from app.payments import models as _payments_models  # noqa: F401
from app.plans import models as _plans_models  # noqa: F401
from app.subscriptions import models as _subscriptions_models  # noqa: F401
from app.webhooks import models as _webhooks_models  # noqa: F401
