"""The Everyticket plan catalog (2026-09 pricing refresh).

Plain data, no ORM - consumed by app.core.seed for fresh databases. An
already-deployed database gets the same catalog from Alembic revision
b3c9e1f47a20, which keeps its own frozen copy of this data on purpose
(a migration must keep meaning what it meant when it shipped, even after
this module is edited later).

Once seeded, plans and features are admin-managed data: an admin edits
them from Admin -> Plans, not by editing this file.

Feature rendering convention on the public Plans page (see
frontend/src/utils/planDisplay.ts):
  - a feature WITH a value is a "highlight" row  (label ... value)
  - a feature WITHOUT a value is a checklist item (check + label)
The plan description (rich text) is rendered as the checklist's heading,
e.g. "Everything in Starter, plus:".
"""

# Plans retired by the pricing refresh. Kept in the DB (subscriptions and
# payments reference them by FK) but inactive, so they disappear from the
# public catalog. Existing subscribers stay on them untouched and can switch
# to a new plan from the portal (plan changes are price-derived, see
# app.subscriptions.service.assert_transition_allowed).
LEGACY_PLAN_CODES = ("BASIC", "PROFESSIONAL", "ENTERPRISE")

# Feature rows (feature_key, feature_label, feature_value) added to the
# existing FREE_TRIAL plan.
FREE_TRIAL_FEATURES: list[tuple[str, str, str | None]] = [
    ("free_tickets", "Free tickets", "Up to 300 / month"),
    ("ticket_overage", "Ticket overage", "₹4 per ticket beyond 300 / month"),
]

PLANS: list[dict] = [
    {
        "plan_code": "STARTER",
        "name": "Starter",
        "description": "<p><strong>Included features</strong></p>",
        "price": 6999,
        "is_contact_sales": False,
        "display_order": 1,
        "features": [
            ("onboarding_charges", "Onboarding charges", "Applicable"),
            ("monthly_ticket_limit", "Monthly ticket limit", "2,000 tickets"),
            ("pos_application", "POS Software Application", None),
            ("staff_accounts", "Active Staff Accounts (5 Users)", None),
            ("payment_methods", "Single Payment Method", None),
            ("analytics", "Basic Analytics with Real-Time Insight", None),
            ("staff_training", "Staff Training One-Time (Included)", None),
            ("event_management", "Event Management", None),
            ("custom_branding", "Basic Custom Branding", None),
            ("admission_app", "Admission App", None),
        ],
    },
    {
        "plan_code": "INSTITUTIONAL",
        "name": "Institutional",
        "description": "<p>Everything in <strong>Starter</strong>, plus:</p>",
        "price": 14999,
        "is_contact_sales": False,
        "display_order": 2,
        "features": [
            ("onboarding_charges", "Onboarding charges", "Applicable"),
            ("monthly_ticket_limit", "Monthly ticket limit", "4,000 tickets"),
            ("ticket_overage", "Ticket overage", "₹4 per ticket beyond 4,000"),
            ("staff_accounts", "Active Staff Accounts (15 Users)", None),
            ("payment_methods", "Multiple Payment Methods", None),
            ("analytics", "AI-led Analytics with Real-Time Insight", None),
            ("staff_training", "Staff Training One-Time (Included)", None),
            ("event_management", "Event Management", None),
            ("custom_branding", "Custom Branding", None),
            ("visitor_behavior_analysis", "Visitor Behavior Analysis", None),
            ("ai_forecasting", "AI-led Forecasting", None),
            ("admission_app", "Admission App", None),
        ],
    },
    {
        "plan_code": "CUSTOM",
        "name": "Custom",
        "description": "<p>Everything in <strong>Institutional</strong>, plus:</p>",
        # No list price - "Talk to us". Must be 0 for a contact-sales plan
        # (see app.api.v1.admin_plans._validate_plan_configuration).
        "price": 0,
        "is_contact_sales": True,
        "display_order": 3,
        "features": [
            ("onboarding_charges", "Onboarding charges", "Applicable"),
            ("monthly_ticket_limit", "Monthly ticket limit", "Talk to us"),
            ("custom_branding", "Custom Branding - Fully Customizable", None),
            ("fundraising_platform", "Donation / Fundraising Platform", None),
            ("email_campaigns", "Marketing / Automation Email Campaigns", None),
            ("white_label_domain", "White-label Custom Domain (additional)", None),
            ("crm_integration", "CRM Integration", None),
        ],
    },
]


# Plan-specific registration questions asked when a customer subscribes or
# switches to the CUSTOM plan (2026-10 follow-up), every time - including
# returning customers. Seeded as starting defaults only: an admin manages
# them afterwards from Admin -> Registration Form ("Show only for plans"),
# where more can be added (e.g. number of venues) without a code change.
# Answers are stored per subscription (CustomerRegistrationData) and sent to
# Everyticket in the subscription.activated webhook payload like any other
# registration field. Alembic revision c4d2a8e61f93 keeps a frozen copy.
CUSTOM_PLAN_FORM_FIELDS: list[dict] = [
    {
        "field_key": "expected_monthly_tickets",
        "label": "Expected tickets per month",
        "field_type": "number",
        "required": True,
        "validation_pattern": r"[0-9]{1,9}",
        "validation_message": "Enter the expected number of tickets per month as a whole number, e.g. 5000",
        "placeholder": "e.g. 5000",
        "help_text": "Roughly how many tickets you expect to sell in a month.",
        "plan_codes": ["CUSTOM"],
        "display_order": 101,
    },
    {
        "field_key": "average_ticket_price",
        "label": "Average ticket price (INR)",
        "field_type": "number",
        "required": True,
        "validation_pattern": r"[0-9]{1,9}(\.[0-9]{1,2})?",
        "validation_message": "Enter the average ticket price in rupees, e.g. 250 or 249.50",
        "placeholder": "e.g. 250",
        "help_text": "Typical price of one ticket, in rupees.",
        "plan_codes": ["CUSTOM"],
        "display_order": 102,
    },
]
