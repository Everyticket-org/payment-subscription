"""Invoice PDF rendering (spec section 45).

Uses reportlab (already a pinned dependency - app/payments/gateways/payu
was the reason it first got added... actually it was added for this
increment; see requirements.txt) via its platypus layer so the layout
reads as a real document rather than a plain text dump - the standing
"keep the frontend/admin panels professional, not MVP-looking" brief
applies just as much to a PDF a customer downloads and may forward to
their own accounts team. Brand colors (#d50355 / #f1e2de) match the rest
of the app.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.invoices.models import Invoice
from app.invoices.schemas import TaxConfigOut

_BRAND_PRIMARY = colors.HexColor("#d50355")
_BRAND_SECONDARY = colors.HexColor("#f1e2de")
_TEXT_DARK = colors.HexColor("#2a1512")


def build_invoice_pdf(
    invoice: Invoice, *, tax_config: TaxConfigOut, seller_name: str = "Everyticket Subscriptions"
) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        title=f"Invoice {invoice.invoice_id}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle", parent=styles["Title"], textColor=colors.white, fontSize=20, leading=24
    )
    label_style = ParagraphStyle("InvoiceLabel", parent=styles["Normal"], textColor=_TEXT_DARK, fontSize=9)
    value_style = ParagraphStyle(
        "InvoiceValue", parent=styles["Normal"], textColor=_TEXT_DARK, fontSize=10, spaceAfter=4
    )
    heading_style = ParagraphStyle(
        "InvoiceHeading", parent=styles["Heading3"], textColor=_BRAND_PRIMARY, fontSize=11, spaceAfter=4
    )

    customer = invoice.customer
    subscription = invoice.subscription
    transaction = invoice.payment_transaction
    plan_name = subscription.plan.name if subscription and subscription.plan else "Subscription"

    elements = []

    # --- Header band (brand color) ---
    header_table = Table(
        [[Paragraph(seller_name, title_style), Paragraph("TAX INVOICE", title_style)]],
        colWidths=[100 * mm, 74 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _BRAND_PRIMARY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (0, 0), 10),
                ("RIGHTPADDING", (1, 0), (1, 0), 10),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 8 * mm))

    # --- Invoice meta + Bill To / Seller, side by side ---
    seller_lines = [f"<b>{seller_name}</b>"]
    if tax_config.seller_gstin:
        seller_lines.append(f"GSTIN: {tax_config.seller_gstin}")

    bill_to_lines = [f"<b>Customer:</b> {customer.customer_id}" if customer else "<b>Customer</b>"]
    if customer:
        bill_to_lines.append(f"Email: {customer.email}")
        bill_to_lines.append(f"Mobile: {customer.mobile}")
    if invoice.gst_number:
        bill_to_lines.append(f"GSTIN: {invoice.gst_number}")

    meta_lines = [
        f"<b>Invoice #:</b> {invoice.invoice_id}",
        f"<b>Invoice date:</b> {invoice.invoice_date.isoformat()}",
        f"<b>Billing period:</b> {invoice.billing_period_start.isoformat()} to {invoice.billing_period_end.isoformat()}",
        f"<b>Payment ref:</b> {transaction.transaction_id if transaction else '-'}",
    ]

    info_table = Table(
        [
            [Paragraph("Seller", heading_style), Paragraph("Bill To", heading_style), Paragraph("Invoice Details", heading_style)],
            [
                Paragraph("<br/>".join(seller_lines), value_style),
                Paragraph("<br/>".join(bill_to_lines), value_style),
                Paragraph("<br/>".join(meta_lines), value_style),
            ],
        ],
        colWidths=[58 * mm, 58 * mm, 58 * mm],
    )
    info_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), _BRAND_SECONDARY),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 8 * mm))

    # --- Line items ---
    rows = [["Description", "Qty", "Unit price", "Amount"]]
    for item in invoice.items:
        rows.append(
            [
                item.description,
                str(item.quantity),
                f"{invoice.currency} {float(item.unit_price):.2f}",
                f"{invoice.currency} {float(item.amount):.2f}",
            ]
        )
    items_table = Table(rows, colWidths=[84 * mm, 20 * mm, 34 * mm, 36 * mm], repeatRows=1)
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _BRAND_PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(items_table)
    elements.append(Spacer(1, 4 * mm))

    # --- Totals ---
    tax_label = tax_config.tax_label or "Tax"
    rate = tax_config.gst_rate_percent
    tax_row_label = f"{tax_label} ({rate:g}%)" if rate else tax_label
    totals_rows = [
        ["", "Subtotal", f"{invoice.currency} {float(invoice.amount):.2f}"],
        ["", tax_row_label, f"{invoice.currency} {float(invoice.tax_amount):.2f}"],
        ["", "Total", f"{invoice.currency} {float(invoice.total_amount):.2f}"],
    ]
    totals_table = Table(totals_rows, colWidths=[104 * mm, 34 * mm, 36 * mm])
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (1, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (1, -1), (-1, -1), 12),
                ("LINEABOVE", (1, -1), (-1, -1), 1, _BRAND_PRIMARY),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    elements.append(totals_table)
    elements.append(Spacer(1, 10 * mm))

    elements.append(
        Paragraph(
            f"Plan: {plan_name} &nbsp;|&nbsp; This is a system-generated invoice and does not require a signature.",
            label_style,
        )
    )

    doc.build(elements)
    return buffer.getvalue()
