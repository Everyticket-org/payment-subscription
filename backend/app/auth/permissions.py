"""
Permission code catalog (spec section 12).

The admin API's require_permission() dependency (app.auth.deps) checks a
caller's roles against these codes. Seeded onto the SUPERADMIN role in
app.core.seed so the dev admin has every permission from day one; a
future admin-user-management screen would let a superadmin assign a
narrower subset of these to other roles (not built yet - see
docs/implementation-status.md).
"""

PERMISSIONS: list[tuple[str, str]] = [
    ("DASHBOARD_VIEW", "View admin dashboard"),
    ("PLANS_MANAGE", "Create/edit/deactivate plans, features, and transitions"),
    ("FORMS_MANAGE", "Create/edit/deactivate dynamic registration-form fields"),
    ("CUSTOMERS_VIEW", "View customer details"),
    ("CUSTOMERS_MANAGE", "Suspend/reactivate customers"),
    ("SUBSCRIPTIONS_VIEW", "View subscriptions and subscription history"),
    ("PAYMENTS_VIEW", "View payment transactions"),
    ("INVOICES_VIEW", "View invoices"),
    ("INVOICES_MANAGE", "Configure invoice GST/tax settings and resend invoice emails with the PDF attached"),
    ("WEBHOOKS_VIEW", "View webhook events and deliveries"),
    ("WEBHOOKS_MANAGE", "Manually retry webhook deliveries"),
    ("NOTIFICATIONS_VIEW", "View notification templates and send logs"),
    ("NOTIFICATIONS_MANAGE", "Edit notification templates"),
    ("AUDIT_VIEW", "View audit logs"),
    ("TESTING_TOOLS_USE", "Use the admin Testing/Developer Tools module (test payments, subscription events, webhook simulation, test email/SSO, test data generation)"),
    ("SYSTEM_CONFIG_VIEW", "View Payment Gateway / Everyticket Integration / Notification / Security / System configuration"),
    ("SYSTEM_CONFIG_MANAGE", "Edit Payment Gateway / Everyticket Integration / Notification / Security / System configuration"),
]
