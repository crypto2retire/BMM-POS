import io
import datetime
from reportlab.lib.units import inch
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

    # Margins and quiet zones
    mx = 0.06 * inch       # horizontal margin for text
    quiet = 0.1 * inch     # barcode quiet zone (min 0.1" per Code128 spec)
    barcode_avail_w = label_w - 2 * quiet  # ~1.18" for barcode bars

    y_cursor = label_h - 0.10 * inch  # start from top

    # 1) Item name — bold 7pt, top of label
    c.setFont("Helvetica-Bold", 7)
    name_display = item_name
    while c.stringWidth(name_display, "Helvetica-Bold", 7) > (label_w - 2 * mx) and len(name_display) > 1:
        name_display = name_display[:-1]
    if len(name_display) < len(item_name):
        name_display = name_display.rstrip() + "…"
    c.drawCentredString(label_w / 2, y_cursor, name_display)

    y_cursor -= 0.14 * inch

    # 2) Price (left, bold 12pt) and Booth (right, bold 10pt)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(mx, y_cursor, price_str)
    if booth_str:
        c.setFont("Helvetica-Bold", 10)
        booth_width = c.stringWidth(booth_str, "Helvetica-Bold", 10)
        c.drawString(label_w - mx - booth_width, y_cursor, booth_str)

    y_cursor -= 0.10 * inch

    # 3) Code128 barcode — fill available width, minimum 0.3" tall
    if raw_barcode:
        barcode_height = 0.38 * inch  # well above 0.3" minimum for scanners

        # Calculate optimal barWidth to fill the available space
        # Code128: each char = 11 modules + start(11) + stop(13) + checksum(11) + 2 quiet
        # For a 6-char barcode: ~101 modules; for 16-char: ~211 modules
        # We want the barcode to fill barcode_avail_w
        probe = code128.Code128(
            raw_barcode,
            barWidth=1.0,  # 1 point per module to measure module count
            barHeight=barcode_height,
            humanReadable=False,
            quiet=False,
        )
        module_count = probe.width  # total width in points = number of modules

        # Target barWidth: fill available width, but cap to prevent thermal bleed
        # Thermal printers cause "dot gain" — bars expand and fill white spaces.
        # 0.010" = 3 dots at 300 DPI — sweet spot for thermal printing.
        target_bar_width = barcode_avail_w / module_count
        min_bar_width = 0.010 * inch  # floor: 3 dots at 300 DPI
        max_bar_width = 0.010 * inch  # cap: prevents thermal bleed on label printers
        bar_width = max(min_bar_width, min(max_bar_width, target_bar_width))

        bc = code128.Code128(
            raw_barcode,
            barWidth=bar_width,
            barHeight=barcode_height,
            humanReadable=False,
            quiet=False,
        )

        bc_x = (label_w - bc.width) / 2
        bc_y = y_cursor - barcode_height
        bc.drawOn(c, bc_x, bc_y)

        # 4) Human-readable barcode text below barcode
        c.setFont("Helvetica-Bold", 6)
        c.drawCentredString(label_w / 2, bc_y - 0.07 * inch, raw_barcode)

    c.showPage()
    c.save()
    return buf.getvalue()


def generate_dymo_xml(item) -> str:
    """Deprecated — use generate_label_pdf() instead."""
    raise NotImplementedError(
        "Dymo XML generation has been replaced by PDF label generation. "
        "Use generate_label_pdf() instead."
    )
