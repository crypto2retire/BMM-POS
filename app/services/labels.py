import io
import datetime
import base64
from PIL import Image, ImageDraw, ImageFont


THERMAL_DPI = 300

CODE39_ALLOWED_CHARS = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%")


def _supports_small_label_code39(barcode_val: str) -> bool:
    if not barcode_val:
        return False
    return all(ch in CODE39_ALLOWED_CHARS for ch in barcode_val.upper())


def _load_label_font(size: int, *, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _code39_decompose(barcode_val: str) -> str:
    from reportlab.graphics.barcode import code39
    barcode = code39.Standard39(barcode_val.upper(), stop=1, checksum=0, quiet=0)
    barcode.validated = barcode.validate()
    barcode.encoded = barcode.encode()
    return barcode.decompose()


def _render_code39_image(barcode_val: str, target_width: int, target_height: int) -> Image.Image:
    pattern = _code39_decompose(barcode_val)
    unit_total = 0
    for token in pattern:
        if token in ("b", "s", "i"):
            unit_total += 1
        elif token in ("B", "S"):
            unit_total += 3

    narrow = max(1, target_width // max(unit_total, 1))
    wide = max(narrow * 3, narrow + 2)
    actual_width = 0
    for token in pattern:
        if token in ("b", "s", "i"):
            actual_width += narrow
        elif token in ("B", "S"):
            actual_width += wide

    img = Image.new("L", (max(actual_width, target_width), max(target_height, 1)), 255)
    draw = ImageDraw.Draw(img)
    x = 0
    for token in pattern:
        if token == "b":
            draw.rectangle([x, 0, x + narrow - 1, target_height], fill=0)
            x += narrow
        elif token == "B":
            draw.rectangle([x, 0, x + wide - 1, target_height], fill=0)
            x += wide
        elif token in ("s", "i"):
            x += narrow
        elif token == "S":
            x += wide

    if img.width > target_width:
        img = img.crop((0, 0, target_width, target_height))
    elif img.width < target_width:
        padded = Image.new("L", (target_width, target_height), 255)
        padded.paste(img, ((target_width - img.width) // 2, 0))
        img = padded
    return img


def _draw_rotated_text(base: Image.Image, text: str, *, box: tuple[int, int, int, int], font_size: int, rotation: int = 90):
    if not text:
        return
    x, y, w, h = box
    font = _load_label_font(font_size, bold=True)
    tmp = Image.new("L", (max(w, 1), max(h, 1)), 255)
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text(((w - text_w) / 2, (h - text_h) / 2), text, font=font, fill=0)
    rotated = tmp.rotate(rotation, expand=True, fillcolor=255)
    paste_x = x + max((w - rotated.width) // 2, 0)
    paste_y = y + max((h - rotated.height) // 2, 0)
    base.paste(rotated, (paste_x, paste_y))


def _generate_small_dymo_label_png(item, booth_number: str) -> bytes:
    width_px = int(round(1.0 * THERMAL_DPI))
    height_px = int(round(1.5 * THERMAL_DPI))
    img = Image.new("L", (width_px, height_px), 255)

    today = datetime.date.today()
    active_price = item.price
    if (
        item.sale_price is not None
        and item.sale_start is not None
        and item.sale_end is not None
        and item.sale_start <= today <= item.sale_end
    ):
        active_price = item.sale_price

    barcode_val = (item.barcode or "").upper()
    price_str = f"${active_price:.2f}"
    booth_str = f"B{booth_number}" if booth_number else ""

    barcode_box = (10, 22, 68, height_px - 40)
    barcode_text_box = (82, 18, 18, height_px - 36)
    booth_box = (103, 18, 30, height_px - 36)
    price_box = (138, 8, width_px - 146, height_px - 16)

    barcode_img = _render_code39_image(barcode_val, barcode_box[2], barcode_box[3])
    img.paste(barcode_img, (barcode_box[0], barcode_box[1]))

    _draw_rotated_text(
        img,
        barcode_val,
        box=barcode_text_box,
        font_size=18,
        rotation=90,
    )
    _draw_rotated_text(
        img,
        booth_str,
        box=booth_box,
        font_size=32,
        rotation=90,
    )
    _draw_rotated_text(
        img,
        price_str,
        box=price_box,
        font_size=54,
        rotation=90,
    )

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _generate_small_dymo_image_xml(item, booth_number: str) -> str:
    png_b64 = base64.b64encode(_generate_small_dymo_label_png(item, booth_number)).decode("ascii")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<DieCutLabel Version="8.0" Units="twips">
  <PaperOrientation>Portrait</PaperOrientation>
  <Id>Address</Id>
  <PaperName>30347 1 in x 1-1/2 in</PaperName>
  <DrawCommands/>
  <ObjectInfo>
    <ImageObject>
      <Name>GRAPHIC</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation0</Rotation>
      <IsMirrored>False</IsMirrored>
      <IsVariable>False</IsVariable>
      <Image>{png_b64}</Image>
      <ScaleMode>Fill</ScaleMode>
      <BorderWidth>0</BorderWidth>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <HorizontalAlignment>Center</HorizontalAlignment>
      <VerticalAlignment>Center</VerticalAlignment>
    </ImageObject>
    <Bounds X="0" Y="0" Width="1440" Height="2160"/>
  </ObjectInfo>
</DieCutLabel>"""


def generate_dymo_xml(item) -> str:
    """Generate Dymo XML for a 30347 (1" x 1.5") label. This is the only label format."""
    import xml.sax.saxutils as saxutils

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
    max_name_len = 35
    name_str = saxutils.escape((item.name or "")[:max_name_len])
    raw_barcode = item.barcode or ""
    barcode_str = saxutils.escape(raw_barcode)
    booth_str = saxutils.escape(f"Booth {booth_number}") if booth_number else ""

    # For Code39-compatible barcodes on 30347, use the pre-rendered image approach
    if _supports_small_label_code39(raw_barcode):
        return _generate_small_dymo_image_xml(item, booth_number)

    # 30347 layout — always portrait, 1" x 1.5"
    label_size = "30347"
    paper_name = "30347 1 in x 1-1/2 in"
    lw = 2160
    lh = 1440

    m = 44
    usable_w = lw - (m * 2)

    portrait_w = lh
    portrait_h = lw
    left_strip_w = int(portrait_w * 0.34)
    right_strip_w = int(portrait_w * 0.28)
    center_w = portrait_w - left_strip_w - right_strip_w
    price_x = portrait_w - right_strip_w + 4
    price_y = m
    price_w = right_strip_w - 8
    price_h = portrait_h - (m * 2)
    booth_x = left_strip_w + int(center_w * 0.18)
    booth_y = m
    booth_w = int(center_w * 0.30)
    booth_h = portrait_h - (m * 2)
    barcode_x = m
    barcode_y = m
    barcode_w = left_strip_w - int(m * 0.35)
    barcode_h = portrait_h - (m * 2)
    barcode_text_x = left_strip_w - 36
    barcode_text_y = m
    barcode_text_w = 32
    barcode_text_h = portrait_h - (m * 2)

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DieCutLabel Version="8.0" Units="twips" MediaType="Default">
  <PaperOrientation>Portrait</PaperOrientation>
  <Id>Address</Id>
  <PaperName>{paper_name}</PaperName>
  <DrawCommands/>
"""

    xml += f"""
  <ObjectInfo>
    <TextObject>
      <Name>PRICE</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation90</Rotation>
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
            <Font Family="Arial" Size="9" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <ObjectLayout>
      <DYMOPoint><X>{price_x}</X><Y>{price_y}</Y></DYMOPoint>
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
      <Rotation>Rotation90</Rotation>
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
            <Font Family="Arial" Size="12" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <ObjectLayout>
      <DYMOPoint><X>{booth_x}</X><Y>{booth_y}</Y></DYMOPoint>
      <Size><Width>{booth_w}</Width><Height>{booth_h}</Height></Size>
      <ZOrder>2</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>"""

    if barcode_str:
        # Code128 quiet zones: 200 twips = 0.139", exceeds 10x module width minimum
        xml += f"""
  <ObjectInfo>
    <BarcodeObject>
      <Name>BARCODE</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation90</Rotation>
      <IsMirrored>False</IsMirrored>
      <IsVariable>False</IsVariable>
      <Text>{barcode_str}</Text>
      <Type>Code128Auto</Type>
      <Size>Medium</Size>
      <TextPosition>None</TextPosition>
      <TextFont Family="Arial" Size="6" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
      <CheckSumFont Family="Arial" Size="6" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
      <TextEmbedding>None</TextEmbedding>
      <ECLevel>0</ECLevel>
      <HorizontalAlignment>Center</HorizontalAlignment>
      <QuietZonesPadding Left="200" Top="0" Right="200" Bottom="0"/>
    </BarcodeObject>
    <ObjectLayout>
      <DYMOPoint><X>{barcode_x}</X><Y>{barcode_y}</Y></DYMOPoint>
      <Size><Width>{barcode_w}</Width><Height>{barcode_h}</Height></Size>
      <ZOrder>3</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>"""

    if barcode_str:
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
      <DYMOPoint><X>{barcode_text_x}</X><Y>{barcode_text_y}</Y></DYMOPoint>
      <Size><Width>{barcode_text_w}</Width><Height>{barcode_text_h}</Height></Size>
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
