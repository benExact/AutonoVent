"""Printable order documents. Every value comes from the stored order."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fpdf import FPDF
from fpdf.fonts import FontFace

from app.models.order import Order, OrderStatusEvent
from app.models.payment import Payment

FONT_DIR = Path(__file__).resolve().parent / "fonts"
JOHANNESBURG = ZoneInfo("Africa/Johannesburg")
NOT_RECORDED = "Not recorded"
SERVICE_NAMES = {"ECO": "Economy", "LSE": "Local Same Day Economy"}
PROVIDER_NAMES = {
    "shiplogic": "ShipLogic",
    "payfast": "PayFast",
    "simulated": "Simulated payment",
    "simulated-courier": "Simulated courier",
    "bobgo": "Bob Go",
}
STATUS_LABELS = {
    "pending": "Pending",
    "paid": "Paid",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "unfulfilled": "Unfulfilled",
    "processing": "Processing",
    "packed": "Packed",
    "shipped": "Shipped",
    "delivered": "Delivered",
}


def document_filename(order_number: str) -> str:
    safe = "".join(character if character.isalnum() or character in "-_" else "-" for character in order_number)
    collapsed = "-".join(part for part in safe.split("-") if part)
    return f"Omniprod-Order-{collapsed or 'order'}.pdf"


def render_order_pdf(order: Order, payments: list[Payment]) -> bytes:
    document = _Document(order.order_number)
    document.alias_nb_pages()
    document.add_page()
    document.summary(order)
    document.customer(order)
    document.delivery(order)
    document.items(order)
    document.totals(order, payments)
    document.additional(order, payments)
    return bytes(document.output())


class _Document(FPDF):
    def __init__(self, order_number: str) -> None:
        super().__init__(format="A4", unit="mm")
        self.order_number = order_number
        self.add_font("DejaVu", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.set_margins(16, 36, 16)
        self.set_auto_page_break(auto=True, margin=18)

    def header(self) -> None:
        self.set_fill_color(31, 45, 31)
        self.rect(0, 0, 210, 28, "F")
        self.set_xy(16, 7)
        self.set_text_color(247, 248, 243)
        self.set_font("DejaVu", "B", 16)
        self.cell(120, 8, "Omniprod")
        self.set_font("DejaVu", "", 11)
        self.set_text_color(217, 201, 169)
        self.cell(0, 8, "Order Details", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_x(16)
        self.set_font("DejaVu", "", 9)
        self.cell(0, 6, "Shop practical products.", new_x="LMARGIN", new_y="NEXT")

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(163, 177, 138)
        self.line(16, self.get_y(), 194, self.get_y())
        self.set_font("DejaVu", "", 8)
        self.set_text_color(86, 107, 47)
        self.cell(0, 8, f"Omniprod  ·  {self.order_number}  ·  Page {self.page_no()} of {{nb}}", align="C")

    def summary(self, order: Order) -> None:
        self.set_xy(self.l_margin, 36)
        self.set_text_color(11, 11, 11)
        self.set_font("DejaVu", "B", 18)
        self.cell(0, 10, order.order_number, new_x="LMARGIN", new_y="NEXT")
        self.set_font("DejaVu", "", 10)
        self._line(f"Order date: {_when(order.created_at)}")
        self._line(f"Payment status: {_status(order.payment_status)}")
        self._line(f"Fulfilment status: {_status(order.fulfilment_status)}")
        if order.is_simulation:
            self._line("This order is marked as a simulated test order.")
        self.ln(2)

    def customer(self, order: Order) -> None:
        self._heading("Customer")
        self._line(f"Name: {order.customer_name}")
        self._line(f"Email: {order.customer_email}")
        self._line(f"Phone: {_text(order.customer_phone)}")

    def delivery(self, order: Order) -> None:
        self._heading("Delivery")
        address = _address(order)
        self._line("Address: " + (address if address else NOT_RECORDED))
        self._line("Courier: " + _courier(order))
        self._line("Shipping cost: " + _money(order.shipping_cents, order.currency))
        self._line("Delivery instructions: " + NOT_RECORDED)

    def items(self, order: Order) -> None:
        self._heading("Items")
        items = sorted(order.items, key=lambda item: (item.product_name, str(item.id)))
        if not items:
            self._line("No items are recorded.")
            return
        heading = FontFace(family="DejaVu", emphasis="BOLD", color=(247, 248, 243), fill_color=(31, 45, 31))
        self.set_font("DejaVu", "", 9)
        self.set_text_color(11, 11, 11)
        self.set_draw_color(163, 177, 138)
        with self.table(
            headings_style=heading,
            line_height=6,
            width=178,
            col_widths=(70, 28, 16, 32, 32),
            text_align=("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"),
        ) as table:
            header = table.row()
            for label in ("Product", "SKU", "Qty", "Unit price", "Line total"):
                header.cell(label)
            for item in items:
                row = table.row()
                row.cell(item.product_name)
                row.cell(_text(item.sku))
                row.cell(str(item.quantity))
                row.cell(_money(item.unit_price_cents, order.currency))
                row.cell(_money(item.line_total_cents, order.currency))
        if any(item.price_is_demo for item in items):
            self.ln(1)
            self._line("A line marked as a test price is not a confirmed selling price.")

    def totals(self, order: Order, payments: list[Payment]) -> None:
        self._heading("Amounts")
        paid = _paid_cents(payments)
        self._line("Subtotal: " + _money(order.subtotal_cents, order.currency))
        self._line("Shipping: " + _money(order.shipping_cents, order.currency))
        self._line("VAT: Included in the stored prices. A separate VAT amount is not recorded.")
        self.set_font("DejaVu", "B", 11)
        self._line("Total payable: " + _money(order.total_cents, order.currency))
        self.set_font("DejaVu", "", 10)
        if paid is None:
            self._line("Amount paid: " + NOT_RECORDED)
            self._line("Outstanding balance: " + NOT_RECORDED)
        else:
            self._line("Amount paid: " + _money(paid, order.currency))
            self._line("Outstanding balance: " + _money(max(order.total_cents - paid, 0), order.currency))

    def additional(self, order: Order, payments: list[Payment]) -> None:
        self._heading("Payment and references")
        latest = _latest_payment(payments)
        self._line("Payment method: " + (_provider(latest.provider) if latest is not None else NOT_RECORDED))
        reference = (latest.provider_reference or "").strip() if latest is not None else ""
        self._line("Transaction reference: " + (reference or NOT_RECORDED))
        self._line("Payment date: " + _payment_date(order, payments))
        if order.shipping_quote_reference:
            self._line("Shipping quote reference: " + order.shipping_quote_reference)
        if order.terms_accepted:
            accepted = _when(order.terms_accepted_at) if order.terms_accepted_at is not None else NOT_RECORDED
            self._line(f"Terms accepted: {order.terms_version or NOT_RECORDED} at {accepted}")
        notes = _notes(order.status_events)
        self._line("Order notes: " + (notes if notes else NOT_RECORDED))

    def _heading(self, title: str) -> None:
        self.ln(3)
        self.set_fill_color(217, 201, 169)
        self.set_text_color(11, 11, 11)
        self.set_font("DejaVu", "B", 11)
        self.cell(0, 8, title, fill=True, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
        self.set_font("DejaVu", "", 10)

    def _line(self, text: str) -> None:
        self.set_x(self.l_margin)
        self.set_text_color(11, 11, 11)
        self.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")


def _money(cents: int, currency: str) -> str:
    sign = "-" if cents < 0 else ""
    amount = abs(int(cents))
    grouped = f"{amount // 100:,}".replace(",", " ")
    prefix = "R " if currency == "ZAR" else f"{currency} "
    return f"{sign}{prefix}{grouped},{amount % 100:02d}"


def _when(value: datetime | None) -> str:
    if value is None:
        return NOT_RECORDED
    moment = value if value.tzinfo is not None else value.replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(JOHANNESBURG).strftime("%d %b %Y, %H:%M SAST")


def _status(value: str) -> str:
    return STATUS_LABELS.get(value, value)


def _text(value: str | None) -> str:
    cleaned = (value or "").strip()
    return cleaned or NOT_RECORDED


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
    return ", ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _provider(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return NOT_RECORDED
    return PROVIDER_NAMES.get(cleaned, cleaned)


def _courier(order: Order) -> str:
    provider = _provider(order.shipping_provider)
    code = (order.shipping_service_code or "").strip()
    if provider == NOT_RECORDED and not code:
        return NOT_RECORDED
    if not code:
        return provider
    name = SERVICE_NAMES.get(code, code)
    if provider == NOT_RECORDED:
        return f"{name} ({code})" if name != code else code
    return f"{provider} · {name} ({code})" if name != code else f"{provider} · {code}"


def _paid_payments(payments: list[Payment]) -> list[Payment]:
    return [payment for payment in payments if payment.status == "paid"]


def _paid_cents(payments: list[Payment]) -> int | None:
    if not payments:
        return None
    return sum(payment.amount_cents for payment in _paid_payments(payments))


def _latest_payment(payments: list[Payment]) -> Payment | None:
    if not payments:
        return None
    return sorted(payments, key=lambda payment: (payment.created_at, str(payment.id)))[-1]


def _payment_date(order: Order, payments: list[Payment]) -> str:
    paid = _paid_payments(payments)
    if paid:
        latest = sorted(paid, key=lambda payment: (payment.created_at, str(payment.id)))[-1]
        return _when(latest.created_at)
    events = [
        event
        for event in order.status_events
        if event.field_name == "payment_status" and event.to_status == "paid"
    ]
    if not events:
        return NOT_RECORDED
    latest_event = sorted(events, key=lambda event: (event.created_at, str(event.id)))[-1]
    return _when(latest_event.created_at)


def _notes(events: list[OrderStatusEvent]) -> str:
    recorded = []
    for event in sorted(events, key=lambda item: (item.created_at, str(item.id))):
        note = (event.note or "").strip()
        if note:
            recorded.append(f"{_when(event.created_at)}: {note}")
    return " ".join(recorded)
