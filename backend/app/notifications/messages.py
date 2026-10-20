"""Customer email content built from the saved order, not from the browser."""

import html
from datetime import datetime, timezone

from app.models.order import Order
from app.models.shipment import Shipment

STATUS_COPY = {
    "processing": "We're preparing your order.",
    "packed": "Your order has been packed and is being prepared for dispatch.",
    "shipped": "Your order has been dispatched.",
    "delivered": "Your order has been marked as delivered.",
    "cancelled": "Your order has been cancelled.",
}


def payment_confirmation(order: Order, *, logo_url: str, sandbox: bool = False) -> tuple[str, str, str]:
    subject = f"Autonovent order {order.order_number} confirmed"
    lines = _item_lines(order)
    address = _address(order)
    when = _when(order.created_at)
    simulation = _simulation_note(order, sandbox=sandbox)
    text = "\n".join(
        [
            "Autonovent",
            "Leave the dust behind.",
            "",
            "Your order has been received and payment is confirmed.",
            simulation,
            f"Order reference: {order.order_number}",
            f"Order date: {when}",
            "",
            "Items",
            *lines,
            "",
            f"Subtotal: {_money(order.subtotal_cents)}",
            f"Delivery: {_money(order.shipping_cents)}",
            f"Total paid: {_money(order.total_cents)}",
            "",
            "Delivery address",
            address,
            "",
            "What happens next",
            "We will email you when your order is being prepared, when it has been packed, when it has been dispatched, and when it has been marked as delivered.",
            "",
            "This message was sent because this address was used at checkout.",
        ]
    )
    body = _html(
        logo_url=logo_url,
        heading="Payment confirmed",
        intro="Your order has been received and payment is confirmed.",
        simulation=simulation,
        rows=[
            ("Order reference", order.order_number),
            ("Order date", when),
            ("Subtotal", _money(order.subtotal_cents)),
            ("Delivery", _money(order.shipping_cents)),
            ("Total paid", _money(order.total_cents)),
        ],
        items=lines,
        address=address,
        explanation="We will email you when your order is being prepared, when it has been packed, when it has been dispatched, and when it has been marked as delivered.",
    )
    return subject, text, body


def fulfilment_update(order: Order, status: str, updated_at: datetime, shipment: Shipment | None, *, logo_url: str) -> tuple[str, str, str]:
    label = status.replace("_", " ").capitalize()
    explanation = STATUS_COPY.get(status, "The fulfilment status of your order has changed.")
    subject = f"Autonovent order {order.order_number} is {label.lower()}"
    when = _when(updated_at)
    simulation = _simulation_note(order, sandbox=order.shipping_provider in {"bobgo", "shiplogic"})
    tracking = ""
    if shipment is not None and shipment.tracking_number:
        tracking = f"Tracking reference: {shipment.tracking_number}"
    text_lines = [
        "Autonovent",
        "Leave the dust behind.",
        "",
        f"Order {order.order_number} is now {label.lower()}.",
        explanation,
        simulation,
        f"Updated: {when}",
    ]
    if tracking:
        text_lines.extend(["", tracking])
    text_lines.extend(["", "This message was sent to the email address saved with the order."])
    text = "\n".join(line for line in text_lines if line is not None)
    rows = [
        ("Order reference", order.order_number),
        ("Status", label),
        ("Updated", when),
    ]
    if tracking:
        rows.append(("Tracking reference", shipment.tracking_number or ""))
    body = _html(
        logo_url=logo_url,
        heading=f"Order {label.lower()}",
        intro=explanation,
        simulation=simulation,
        rows=rows,
        items=[],
        address="",
        explanation="This update was sent because the order status changed. It does not change the payment status.",
    )
    return subject, text, body


def _html(
    *,
    logo_url: str,
    heading: str,
    intro: str,
    simulation: str,
    rows: list[tuple[str, str]],
    items: list[str],
    address: str,
    explanation: str,
) -> str:
    logo = ""
    if logo_url.strip():
        logo = f'<img src="{_esc(logo_url.strip())}" alt="Autonovent" width="160" style="display:block;height:auto;border:0;">'
    else:
        logo = '<p style="margin:0;font-size:22px;letter-spacing:0.08em;text-transform:uppercase;">Autonovent</p>'
    detail_rows = "".join(
        f"<tr><td style=\"padding:8px 12px 8px 0;color:#A3B18A;\">{_esc(name)}</td><td style=\"padding:8px 0;\">{_esc(value)}</td></tr>"
        for name, value in rows
    )
    item_html = ""
    if items:
        item_html = "<ul style=\"margin:16px 0;padding-left:18px;\">" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"
    address_html = ""
    if address:
        address_html = f"<p style=\"margin:16px 0 0;\"><strong>Delivery address</strong><br>{_esc(address).replace(chr(10), '<br>')}</p>"
    simulation_html = f"<p style=\"margin:16px 0;padding:12px;background:#1F2D1F;color:#D9C9A9;\">{_esc(simulation)}</p>" if simulation else ""
    return f"""<!DOCTYPE html>
<html lang="en">
  <body style="margin:0;padding:0;background:#0B0B0B;color:#F7F8F3;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0B0B0B;">
      <tr>
        <td align="center" style="padding:24px 12px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#1F2D1F;border-radius:8px;">
            <tr>
              <td style="padding:28px 24px;color:#F7F8F3;">
                {logo}
                <p style="margin:8px 0 0;color:#A3B18A;">Leave the dust behind.</p>
                <h1 style="margin:24px 0 8px;font-size:24px;line-height:1.3;">{_esc(heading)}</h1>
                <p style="margin:0;line-height:1.5;">{_esc(intro)}</p>
                {simulation_html}
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:8px;">{detail_rows}</table>
                {item_html}
                {address_html}
                <p style="margin:20px 0 0;line-height:1.5;">{_esc(explanation)}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


def _item_lines(order: Order) -> list[str]:
    items = sorted(order.items, key=lambda item: item.product_name)
    return [f"{item.quantity} × {item.product_name}" for item in items]


def _address(order: Order) -> str:
    parts = [
        order.delivery_name,
        order.delivery_line1,
        order.delivery_line2,
        order.delivery_suburb,
        order.delivery_city,
        order.delivery_region,
        order.delivery_postal_code,
        order.delivery_country,
    ]
    return "\n".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _simulation_note(order: Order, *, sandbox: bool = False) -> str:
    if order.is_simulation:
        return "This is a simulated test order. The payment is not a PayFast payment, and the delivery amount is not a courier price."
    if sandbox and order.shipping_provider == "bobgo":
        return "This is a PayFast sandbox transaction. It is not a live sale, and the delivery quote is a Bob Go sandbox rate."
    if sandbox:
        return "This is a PayFast sandbox transaction. It is not a live sale, and the delivery quote is a ShipLogic sandbox rate."
    return ""


def _money(cents: int) -> str:
    return f"R{cents / 100:,.2f}"


def _when(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%d %B %Y, %H:%M UTC")


def _esc(value: str) -> str:
    return html.escape(value, quote=True)
