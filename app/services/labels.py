import io
import os
import tempfile
from decimal import Decimal
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.graphics.barcode import code128


LABEL_WIDTH = 2.25 * inch
LABEL_HEIGHT = 1.25 * inch


def generate_label_pdf(item) -> bytes:
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
    _draw_label(c, item, 0, 0)
    c.save()
    return buffer.getvalue()


def generate_label_sheet(items) -> bytes:
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
    for i, item in enumerate(items):
        if i > 0:
            c.showPage()
        _draw_label(c, item, 0, 0)
    c.save()
    return buffer.getvalue()


def _draw_label(c, item, x_offset, y_offset):
    margin = 0.08 * inch
    w = LABEL_WIDTH
    h = LABEL_HEIGHT

    name = item.name[:30] if item.name else ""
    c.setFont("Helvetica-Bold", 7)
    c.drawString(margin, h - margin - 7, name)

    booth = getattr(item, "vendor", None)
    booth_number = ""
    if booth:
        booth_number = getattr(booth, "booth_number", "") or ""

    today = __import__("datetime").date.today()
    active_price = item.price
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        active_price = item.sale_price

    price_str = f"${active_price:.2f}"
    c.setFont("Helvetica-Bold", 9)
    c.drawString(margin, h - margin - 18, price_str)

    if booth_number:
        c.setFont("Helvetica", 6)
        c.drawRightString(w - margin, h - margin - 7, f"Booth: {booth_number}")

    barcode_obj = code128.Code128(item.barcode, barHeight=0.3 * inch, barWidth=0.8)
    barcode_w = barcode_obj.width
    barcode_x = (w - barcode_w) / 2
    barcode_obj.drawOn(c, barcode_x, margin + 4)

    c.setFont("Helvetica", 5)
    c.drawCentredString(w / 2, margin, item.barcode)
