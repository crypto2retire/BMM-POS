import io
import math
import datetime
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode import code39


THERMAL_DPI = 203
DOT = 72.0 / THERMAL_DPI

LABEL_SIZES = {
    "1.5x1":     {"name": "1\" x 1.5\" (DYMO 30347 / PDF Preview)", "w": 1.5, "h": 1.0},
    "2.125x1":   {"name": "1\" x 2-1/8\" (DYMO 30336 / PDF Preview)", "w": 2.125, "h": 1.0},
    "2.25x1.25": {"name": "2.25\" x 1.25\" (Thermal/Standard)", "w": 2.25, "h": 1.25},
    "2.625x1":   {"name": "2-5/8\" x 1\" (Avery 5160/8160)", "w": 2.625, "h": 1.0},
    "4x2":       {"name": "4\" x 2\" (Avery 5163/Shipping)", "w": 4.0, "h": 2.0},
    "4x1.33":    {"name": "4\" x 1-1/3\" (Avery 5162)", "w": 4.0, "h": 1.33},
    "4x3.33":    {"name": "4\" x 3-1/3\" (Avery 5164)", "w": 4.0, "h": 3.33},
    "1.75x0.5":  {"name": "1-3/4\" x 1/2\" (Avery 5167)", "w": 1.75, "h": 0.5},
    "3.5x1.125": {"name": "3-1/2\" x 1-1/8\" (Avery 8462)", "w": 3.5, "h": 1.125},
    "2x2":       {"name": "2\" x 2\" (Square)", "w": 2.0, "h": 2.0},
    "3x2":       {"name": "3\" x 2\" (Medium)", "w": 3.0, "h": 2.0},
    "2x1":       {"name": "2\" x 1\" (Small)", "w": 2.0, "h": 1.0},
}

DEFAULT_LABEL_SIZE = "2.25x1.25"
DYMO_TO_PDF_SIZE = {
    "30347": "1.5x1",
    "30336": "2.125x1",
    "30252": "3.5x1.125",
}

CODE39_ALLOWED_CHARS = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%")


def _get_label_dims(size_key):
    spec = LABEL_SIZES.get(size_key, LABEL_SIZES[DEFAULT_LABEL_SIZE])
    return spec["w"] * inch, spec["h"] * inch


def resolve_pdf_label_size(
    requested_size: str | None = None,
    *,
    label_preference: str | None = None,
    dymo_size: str | None = None,
    fallback_size: str | None = None,
) -> str:
    if requested_size in LABEL_SIZES:
        return requested_size
    if label_preference == "dymo":
        mapped = DYMO_TO_PDF_SIZE.get(dymo_size or "30347")
        if mapped in LABEL_SIZES:
            return mapped
    if fallback_size in LABEL_SIZES:
        return fallback_size
    return DEFAULT_LABEL_SIZE


def _snap_down(val):
    return math.floor(val / DOT) * DOT


def _snap_up(val):
    return math.ceil(val / DOT) * DOT


def _fit_bar_width(usable_w, probe_width):
    if usable_w <= 0 or probe_width <= 0:
        return DOT
    fit_bar_w = usable_w / probe_width
    snapped = max(round(fit_bar_w / DOT), 1) * DOT
    while snapped > DOT and (probe_width * snapped) > usable_w:
        snapped -= DOT
    return max(snapped, DOT)


def _minimum_small_label_bar_width(barcode_val, usable_w, probe_width):
    if not barcode_val or usable_w <= 0 or probe_width <= 0:
        return DOT
    preferred = 2 * DOT
    if (probe_width * preferred) <= usable_w:
        return preferred
    return DOT


def _supports_small_label_code39(barcode_val: str) -> bool:
    if not barcode_val:
        return False
    return all(ch in CODE39_ALLOWED_CHARS for ch in barcode_val.upper())


def _build_pdf_barcode(barcode_val: str, *, small_label: bool, usable_w: float, bar_h: float):
    if small_label and _supports_small_label_code39(barcode_val):
        probe = code39.Standard39(
            barcode_val.upper(),
            barHeight=10,
            stop=1,
            checksum=0,
            quiet=0,
        )
        probe_width = probe.width
        bar_w = _fit_bar_width(usable_w, probe_width)
        bar_w = max(bar_w, _minimum_small_label_bar_width(barcode_val, usable_w, probe_width))
        barcode_obj = code39.Standard39(
            barcode_val.upper(),
            barHeight=bar_h,
            stop=1,
            checksum=0,
            quiet=0,
            barWidth=bar_w,
        )
        return barcode_obj

    probe = code128.Code128(
        barcode_val,
        barHeight=10,
        barWidth=1.0,
        humanReadable=False,
        quiet=False,
    )
    probe_width = probe.width
    bar_w = _fit_bar_width(usable_w, probe_width)
    if small_label:
        bar_w = max(bar_w, _minimum_small_label_bar_width(barcode_val, usable_w, probe_width))
    barcode_obj = code128.Code128(
        barcode_val,
        barHeight=bar_h,
        barWidth=bar_w,
        humanReadable=False,
        quiet=False,
    )
    return barcode_obj


def generate_label_pdf(item, label_size=None) -> bytes:
    lw, lh = _get_label_dims(label_size)
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=(lw, lh))
    _draw_label(c, item, 0, 0, lw, lh)
    c.save()
    return buffer.getvalue()


def generate_label_sheet(items, label_size=None) -> bytes:
    lw, lh = _get_label_dims(label_size)
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=(lw, lh))
    for i, item in enumerate(items):
        if i > 0:
            c.showPage()
        _draw_label(c, item, 0, 0, lw, lh)
    c.save()
    return buffer.getvalue()


def _draw_label(c, item, x_offset, y_offset, w=None, h=None):
    if w is None:
        w = 2.25 * inch
    if h is None:
        h = 1.25 * inch

    ref_w = 2.25 * inch
    ref_h = 1.25 * inch
    scale_w = w / ref_w
    scale_h = h / ref_h
    scale = min(scale_w, scale_h)
    small_label = w <= (1.6 * inch) and h <= (1.05 * inch)

    margin = _snap_up(max(2 if small_label else 3, (2.5 if small_label else 3) * scale))

    inner_left = _snap_up(margin + (2 if small_label else 3) * scale)
    inner_right = _snap_down(w - margin - (2 if small_label else 3) * scale)

    booth = getattr(item, "vendor", None)
    booth_number = ""
    if booth:
        booth_number = getattr(booth, "booth_number", "") or ""

    if small_label:
        divider_y = _snap_down(h - margin - (2.5 * scale_h))
    else:
        name = (item.name or "")[:50 if scale > 1.2 else 40]
        name_y = _snap_down(h - margin - 13 * scale_h)

        base_name_size = 11
        if len(name) > 28:
            base_name_size = 8
        elif len(name) > 20:
            base_name_size = 10
        name_size = max(6, min(24, base_name_size * scale))
        c.setFont("Helvetica-Bold", name_size)
        c.drawString(inner_left, name_y, name)

        divider_y = _snap_down(name_y - 5 * scale_h)
        c.setStrokeColorRGB(0.4, 0.4, 0.4)
        c.setLineWidth(DOT)
        c.line(inner_left, divider_y, inner_right, divider_y)

    today = datetime.date.today()
    active_price = item.price
    on_sale = False
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        active_price = item.sale_price
        on_sale = True

    price_str = f"${active_price:.2f}"
    price_size = max(8 if small_label else 8, min(28, (10.5 if small_label else 14) * scale))
    price_y = _snap_down((h - margin - (13 if small_label else 16) * scale_h) if small_label else (divider_y - 16 * scale_h))
    c.setFont("Helvetica-Bold", price_size)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(inner_left, price_y, price_str)

    if on_sale and not small_label:
        orig_str = f"${item.price:.2f}"
        price_w = c.stringWidth(price_str, "Helvetica-Bold", price_size)
        orig_size = max(5.5 if small_label else 6, min(16, (7 if small_label else 8) * scale))
        c.setFont("Helvetica", orig_size)
        c.setFillColorRGB(0.35, 0.35, 0.35)
        orig_x = _snap_up(inner_left + price_w + 4 * scale_w)
        c.drawString(orig_x, price_y + DOT, orig_str)
        orig_w = c.stringWidth(orig_str, "Helvetica", orig_size)
        c.setStrokeColorRGB(0.35, 0.35, 0.35)
        c.setLineWidth(DOT)
        strike_y = _snap_down(price_y + (4 if small_label else 4.5) * scale_h)
        c.line(orig_x, strike_y, orig_x + orig_w, strike_y)
        c.setFillColorRGB(0, 0, 0)

    if booth_number:
        booth_size = max(7.5 if small_label else price_size, min(price_size, (9 if small_label else price_size)))
        c.setFont("Helvetica-Bold", booth_size)
        c.drawRightString(inner_right, price_y, "B" + booth_number)

    barcode_val = item.barcode or ""
    if barcode_val:
        avail_w = w - margin * 2

        barcode_text_size = max(6 if small_label else 6, min(16, (7 if small_label else 10) * scale))
        barcode_text_y = _snap_up(margin + (1 if small_label else 1) * scale_h)
        barcode_y = _snap_up(barcode_text_y + (11 if small_label else 14) * scale_h)

        min_bar_h = _snap_down((0.54 if small_label else 0.32) * inch * scale_h)
        bar_h = _snap_down((price_y - 5 * scale_h - barcode_y) if small_label else (price_y - 8 * scale_h - barcode_y))
        bar_h = max(bar_h, min_bar_h)

        # Keep quiet zones, but keep them tighter on the smallest label.
        quiet_zone = (10 if small_label else 10) * DOT
        usable_w = avail_w - quiet_zone * 2

        barcode_obj = _build_pdf_barcode(
            barcode_val,
            small_label=small_label,
            usable_w=usable_w,
            bar_h=bar_h,
        )

        barcode_w = barcode_obj.width
        barcode_x = _snap_down((w - barcode_w) / 2)
        barcode_obj.drawOn(c, barcode_x, barcode_y)

        c.setFont("Helvetica-Bold", barcode_text_size)
        c.drawCentredString(w / 2, barcode_text_y, barcode_val)


def generate_dymo_xml(item, label_size: str = None) -> str:
    import xml.sax.saxutils as saxutils

    if not label_size:
        from app.config import settings
        label_size = settings.dymo_label_size

    booth_number = ""
    vendor = getattr(item, "vendor", None)
    if vendor:
        booth_number = getattr(vendor, "booth_number", "") or ""

    today = datetime.date.today()
    active_price = item.price
    on_sale = False
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        active_price = item.sale_price
        on_sale = True

    price_str = saxutils.escape(f"${active_price:.2f}")
    if on_sale and label_size != "30347":
        price_str += saxutils.escape(f"  (was ${item.price:.2f})")
    max_name_len = 35
    name_str = saxutils.escape((item.name or "")[:max_name_len])
    raw_barcode = item.barcode or ""
    barcode_str = saxutils.escape(raw_barcode)
    booth_str = saxutils.escape(f"Booth {booth_number}") if booth_number else ""

    DYMO_PAPER = {
        "30252": {"name": "30252 Address",                "w": 5040, "h": 1620},
        "30336": {"name": "30336 Small Address",          "w": 3060, "h": 1440},
        "30347": {"name": "30347 1 in x 1-1/2 in",       "w": 2160, "h": 1440},
    }
    spec = DYMO_PAPER.get(label_size, DYMO_PAPER["30347"])
    paper_name = spec["name"]
    lw = spec["w"]
    lh = spec["h"]
    is_small_dymo = label_size == "30347"

    m = 44 if is_small_dymo else 60
    usable_w = lw - (m * 2)

    if is_small_dymo:
        name_y = 0
        name_h = 0
        price_y = lh - m - int(lh * 0.11)
        price_h = int(lh * 0.11)
        price_w = int(usable_w * 0.54)
        booth_w = usable_w - price_w - 12
        barcode_text_h = int(lh * 0.085)
        barcode_text_y = m
        barcode_y = barcode_text_y + barcode_text_h + 10
        barcode_h = price_y - barcode_y - 12
        barcode_h = max(barcode_h, int(lh * 0.60))
    else:
        name_y = lh - m - 10
        name_h = int(lh * 0.18)
        price_w = int(usable_w * 0.55)
        booth_w = usable_w - price_w - 20
        price_y = name_y - name_h - 5
        price_h = int(lh * 0.16)
        barcode_h = lh - m - (name_h + price_h + 30) - m
        barcode_h = max(barcode_h, int(lh * 0.46))
        barcode_y = m
        barcode_text_h = 0
        barcode_text_y = 0

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DieCutLabel Version="8.0" Units="twips" MediaType="Default">
  <PaperOrientation>Landscape</PaperOrientation>
  <Id>Address</Id>
  <PaperName>{paper_name}</PaperName>
  <DrawCommands/>
"""

    if not is_small_dymo:
        xml += f"""
  <ObjectInfo>
    <TextObject>
      <Name>NAME</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation0</Rotation>
      <IsMirrored>False</IsMirrored>
      <IsVariable>False</IsVariable>
      <HorizontalAlignment>Left</HorizontalAlignment>
      <VerticalAlignment>Middle</VerticalAlignment>
      <TextFitMode>ShrinkToFit</TextFitMode>
      <UseFullFontHeight>True</UseFullFontHeight>
      <Verticalized>False</Verticalized>
      <StyledText>
        <Element>
          <String>{name_str}</String>
          <Attributes>
            <Font Family="Arial" Size="{'9' if is_small_dymo else '14'}" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <ObjectLayout>
      <DYMOPoint><X>{m}</X><Y>{name_y}</Y></DYMOPoint>
      <Size><Width>{usable_w}</Width><Height>{name_h}</Height></Size>
      <ZOrder>0</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>"""

    xml += f"""
  <ObjectInfo>
    <TextObject>
      <Name>PRICE</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation0</Rotation>
      <IsMirrored>False</IsMirrored>
      <IsVariable>False</IsVariable>
      <HorizontalAlignment>Left</HorizontalAlignment>
      <VerticalAlignment>Middle</VerticalAlignment>
      <TextFitMode>ShrinkToFit</TextFitMode>
      <UseFullFontHeight>True</UseFullFontHeight>
      <Verticalized>False</Verticalized>
      <StyledText>
        <Element>
          <String>{price_str}</String>
          <Attributes>
            <Font Family="Arial" Size="{'9' if is_small_dymo else '14'}" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <ObjectLayout>
      <DYMOPoint><X>{m}</X><Y>{price_y}</Y></DYMOPoint>
      <Size><Width>{price_w}</Width><Height>{price_h}</Height></Size>
      <ZOrder>1</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>"""

    if booth_str:
        xml += f"""
  <ObjectInfo>
    <TextObject>
      <Name>BOOTH</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation0</Rotation>
      <IsMirrored>False</IsMirrored>
      <IsVariable>False</IsVariable>
      <HorizontalAlignment>Right</HorizontalAlignment>
      <VerticalAlignment>Middle</VerticalAlignment>
      <TextFitMode>ShrinkToFit</TextFitMode>
      <UseFullFontHeight>True</UseFullFontHeight>
      <Verticalized>False</Verticalized>
      <StyledText>
        <Element>
          <String>{booth_str}</String>
          <Attributes>
            <Font Family="Arial" Size="{'8' if is_small_dymo else '10'}" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <ObjectLayout>
      <DYMOPoint><X>{m + price_w + 20}</X><Y>{price_y}</Y></DYMOPoint>
      <Size><Width>{booth_w}</Width><Height>{price_h}</Height></Size>
      <ZOrder>2</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>"""

    if barcode_str:
        small_dymo_uses_code39 = is_small_dymo and _supports_small_label_code39(raw_barcode)
        dymo_barcode_type = "Code39" if small_dymo_uses_code39 else "Code128Auto"
        dymo_barcode_size = "Medium" if small_dymo_uses_code39 else "Large"
        dymo_quiet_zone = "0" if small_dymo_uses_code39 else "14"
        xml += f"""
  <ObjectInfo>
    <BarcodeObject>
      <Name>BARCODE</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation0</Rotation>
      <IsMirrored>False</IsMirrored>
      <IsVariable>False</IsVariable>
      <Text>{barcode_str}</Text>
      <Type>{dymo_barcode_type}</Type>
      <Size>{dymo_barcode_size}</Size>
      <TextPosition>{'None' if is_small_dymo else 'Bottom'}</TextPosition>
      <TextFont Family="Arial" Size="{'6' if is_small_dymo else '7'}" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
      <CheckSumFont Family="Arial" Size="{'6' if is_small_dymo else '7'}" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
      <TextEmbedding>None</TextEmbedding>
      <ECLevel>0</ECLevel>
      <HorizontalAlignment>Center</HorizontalAlignment>
      <QuietZonesPadding Left="{dymo_quiet_zone}" Top="0" Right="{dymo_quiet_zone}" Bottom="0"/>
    </BarcodeObject>
    <ObjectLayout>
      <DYMOPoint><X>{m}</X><Y>{barcode_y}</Y></DYMOPoint>
      <Size><Width>{usable_w}</Width><Height>{barcode_h}</Height></Size>
      <ZOrder>3</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>"""

    if barcode_str and is_small_dymo:
        xml += f"""
  <ObjectInfo>
    <TextObject>
      <Name>BARCODE_TEXT</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation0</Rotation>
      <IsMirrored>False</IsMirrored>
      <IsVariable>False</IsVariable>
      <HorizontalAlignment>Center</HorizontalAlignment>
      <VerticalAlignment>Middle</VerticalAlignment>
      <TextFitMode>ShrinkToFit</TextFitMode>
      <UseFullFontHeight>True</UseFullFontHeight>
      <Verticalized>False</Verticalized>
      <StyledText>
        <Element>
          <String>{barcode_str}</String>
          <Attributes>
            <Font Family="Arial" Size="8" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <ObjectLayout>
      <DYMOPoint><X>{m}</X><Y>{barcode_text_y}</Y></DYMOPoint>
      <Size><Width>{usable_w}</Width><Height>{barcode_text_h}</Height></Size>
      <ZOrder>4</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>"""

    xml += """
</DieCutLabel>"""
    return xml
