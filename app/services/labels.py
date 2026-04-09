import io
import datetime
import xml.sax.saxutils as saxutils
from reportlab.lib.units import inch
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128


def generate_label_pdf(item) -> bytes:
    """Generate a 1.5" x 1" PDF label for browser-based printing.

    Bypasses the Dymo SDK entirely — the user prints via File > Print
    with the Dymo printer selected. Works with ANY label printer.
    """
    booth_number = ""
    vendor = getattr(item, "vendor", None)
    if vendor:
        booth_number = getattr(vendor, "booth_number", "") or ""

    today = datetime.date.today()
    active_price = item.price
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        active_price = item.sale_price

    price_str = f"${active_price:.2f}"
    raw_barcode = item.barcode or ""
    booth_str = f"B{booth_number}" if booth_number else ""
    item_name = (item.name or "")[:35]

    # Label dimensions: 1.5" wide x 1.0" tall
    label_w = 1.5 * inch
    label_h = 1.0 * inch

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(label_w, label_h))

    # Margins
    mx = 0.06 * inch  # horizontal margin
    quiet = 0.1 * inch  # barcode quiet zone

    # Y positions (bottom-up in PDF coordinate system)
    # Bottom: barcode text at ~0.04"
    # Then: barcode above that
    # Then: price/booth line
    # Top: item name

    y_cursor = label_h - 0.12 * inch  # start from top

    # 1) Item name — bold 7pt, top of label
    c.setFont("Helvetica-Bold", 7)
    # Truncate to fit width
    name_display = item_name
    while c.stringWidth(name_display, "Helvetica-Bold", 7) > (label_w - 2 * mx) and len(name_display) > 1:
        name_display = name_display[:-1]
    if len(name_display) < len(item_name):
        name_display = name_display.rstrip() + "…"
    c.drawCentredString(label_w / 2, y_cursor, name_display)

    y_cursor -= 0.15 * inch

    # 2) Price (left, bold 12pt) and Booth (right, bold 10pt)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(mx, y_cursor, price_str)
    if booth_str:
        c.setFont("Helvetica-Bold", 10)
        booth_width = c.stringWidth(booth_str, "Helvetica-Bold", 10)
        c.drawString(label_w - mx - booth_width, y_cursor, booth_str)

    y_cursor -= 0.12 * inch

    # 3) Code128 barcode — centered with quiet zones
    if raw_barcode:
        barcode_avail_w = label_w - 2 * quiet
        barcode_height = 0.32 * inch

        bc = code128.Code128(
            raw_barcode,
            barWidth=0.008 * inch,
            barHeight=barcode_height,
            humanReadable=False,
            quiet=False,
        )

        # Scale to fit if needed
        bc_actual_w = bc.width
        if bc_actual_w > barcode_avail_w:
            scale = barcode_avail_w / bc_actual_w
            bc.barWidth = bc.barWidth * scale
            bc = code128.Code128(
                raw_barcode,
                barWidth=bc.barWidth,
                barHeight=barcode_height,
                humanReadable=False,
                quiet=False,
            )
            bc_actual_w = bc.width

        bc_x = (label_w - bc_actual_w) / 2
        bc_y = y_cursor - barcode_height
        bc.drawOn(c, bc_x, bc_y)

        # 4) Human-readable barcode text below barcode
        c.setFont("Helvetica", 5)
        c.drawCentredString(label_w / 2, bc_y - 0.06 * inch, raw_barcode)

    c.showPage()
    c.save()
    return buf.getvalue()


# Keep generate_dymo_xml as a thin wrapper for backward compat if anything
# still references it, but the router should call generate_label_pdf directly.
def generate_dymo_xml(item) -> str:
    """Deprecated — use generate_label_pdf() instead."""
    raise NotImplementedError(
        "Dymo XML generation has been replaced by PDF label generation. "
        "Use generate_label_pdf() instead."
    )
