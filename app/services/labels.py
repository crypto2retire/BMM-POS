import io
import math
import datetime
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128


# Label dimensions: Dymo 30347 — 1.5"W × 1.0"H landscape (barcode runs long way)
_LABEL_W = 1.5 * inch
_LABEL_H = 1.0 * inch

# Thermal printer dot size at 300 DPI
_DOT = 1 / 300 * inch


def _snap_down(val: float) -> float:
    """Snap a coordinate down to the nearest printer dot boundary."""
    return math.floor(val / _DOT) * _DOT


def _snap_up(val: float) -> float:
    """Snap a coordinate up to the nearest printer dot boundary."""
    return math.ceil(val / _DOT) * _DOT


def _draw_single_label(c: canvas.Canvas, item) -> None:
    """Draw one label onto the current page of canvas c.

    Layout for 1.5"W × 1.0"H landscape label (Dymo 450):
    - Single compact text line: booth (left), name (center), price (right)
    - Code128 barcode filling maximum available width and height
    - Human-readable barcode text at bottom

    Used by both the single-label path (generate_label_pdf) and the
    batch path (generate_label_pdf_batch) so both paths render
    identically on the Dymo LabelWriter 450.
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

    mx = 0.04 * inch       # horizontal margin for text (tight)
    quiet = 0.10 * inch    # Code128 minimum practical quiet zone (30 dots)

    # ── Top text band: one line with booth (left), name (center), price (right) ──
    text_top = _LABEL_H - 0.05 * inch
    text_band_h = 0.11 * inch  # height consumed by text band

    c.setFont("Helvetica-Bold", 6)
    if booth_str:
        c.drawString(mx, text_top, booth_str)

    c.setFont("Helvetica-Bold", 5)
    name_display = item_name
    price_width = c.stringWidth(price_str, "Helvetica-Bold", 9) + 0.03 * inch
    booth_width = c.stringWidth(booth_str, "Helvetica-Bold", 6) + 0.03 * inch if booth_str else 0
    name_max_w = _LABEL_W - mx - booth_width - price_width - mx
    while c.stringWidth(name_display, "Helvetica-Bold", 5) > name_max_w and len(name_display) > 1:
        name_display = name_display[:-1]
    if len(name_display) < len(item_name):
        name_display = name_display.rstrip() + "…"
    c.drawCentredString(_LABEL_W / 2, text_top, name_display)

    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(_LABEL_W - mx, text_top, price_str)

    # ── Bottom text: human-readable barcode ──
    bottom_text_h = 0.07 * inch  # space for barcode digits at bottom

    # ── Barcode: fill all remaining vertical space ──
    if raw_barcode:
        barcode_top = _LABEL_H - text_band_h
        barcode_bottom = bottom_text_h
        barcode_height = barcode_top - barcode_bottom

        # Measure module count using a 1-point-per-module probe
        probe = code128.Code128(
            raw_barcode,
            barWidth=1.0,
            barHeight=barcode_height,
            humanReadable=False,
            quiet=False,
        )
        module_count = probe.width

        # Calculate barWidth to fill available width between quiet zones.
        # Snap UP to dot boundary so bars are as wide as possible.
        barcode_avail_w = _LABEL_W - 2 * quiet
        raw_bar_w = barcode_avail_w / module_count
        # Snap DOWN so barcode fits within avail_w; floor at 3 dots (0.010") for thermal scan
        bar_w = max(math.floor(raw_bar_w / _DOT), 3) * _DOT

        bc = code128.Code128(
            raw_barcode,
            barWidth=bar_w,
            barHeight=barcode_height,
            humanReadable=False,
            quiet=False,
        )

        # Position barcode: center horizontally, bottom edge at barcode_bottom
        actual_bc_w = module_count * bar_w
        bc_x = (_LABEL_W - actual_bc_w) / 2
        bc_x = _snap_down(bc_x)
        bc_y = barcode_bottom
        bc.drawOn(c, bc_x, bc_y)

        # Human-readable barcode text at very bottom
        c.setFont("Helvetica-Bold", 5)
        c.drawCentredString(_LABEL_W / 2, 0.015 * inch, raw_barcode)


def generate_label_pdf(item) -> bytes:
    """Generate a 1.5"W × 1.0"H single-label PDF for browser-based printing.

    Bypasses the Dymo SDK entirely — the user prints via File > Print
    with the Dymo printer selected. Works with ANY label printer.
    Used by the per-card/per-row single-label "Print Label" fallback.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(_LABEL_W, _LABEL_H))
    _draw_single_label(c, item)
    c.showPage()
    c.save()
    return buf.getvalue()


def generate_label_pdf_batch(items) -> bytes:
    """Generate a multi-page 1.5"W × 1.0"H PDF, one label per page.

    Shares the exact same precision drawing logic as the single-label
    path (_draw_single_label) so batch-printed labels are pixel-
    identical to single-printed labels. Used by the "Print Labels"
    batch workflow on the vendor items page.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(_LABEL_W, _LABEL_H))
    for item in items:
        _draw_single_label(c, item)
        c.showPage()
    c.save()
    return buf.getvalue()


def generate_dymo_xml(item) -> str:
    """Deprecated — use generate_label_pdf() instead."""
    raise NotImplementedError(
        "Dymo XML generation has been replaced by PDF label generation. "
        "Use generate_label_pdf() instead."
    )
