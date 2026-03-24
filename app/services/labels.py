import io
import datetime
from reportlab.lib.units import inch
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
    w = LABEL_WIDTH
    h = LABEL_HEIGHT
    margin = 4

    c.setStrokeColorRGB(0.15, 0.15, 0.15)
    c.setLineWidth(0.6)
    c.rect(margin, margin, w - margin * 2, h - margin * 2)

    inner_left = margin + 5
    inner_right = w - margin - 5

    name = (item.name or "")[:36]
    name_y = h - margin - 14

    booth = getattr(item, "vendor", None)
    booth_number = ""
    if booth:
        booth_number = getattr(booth, "booth_number", "") or ""

    if len(name) > 22:
        c.setFont("Helvetica-Bold", 8)
    elif len(name) > 16:
        c.setFont("Helvetica-Bold", 9.5)
    else:
        c.setFont("Helvetica-Bold", 11)
    c.drawString(inner_left, name_y, name)

    if booth_number:
        c.setFont("Helvetica", 8)
        c.drawRightString(inner_right, name_y, f"Booth {booth_number}")

    divider_y = name_y - 5
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    c.setLineWidth(0.3)
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
    price_y = divider_y - 16
    c.setFont("Helvetica-Bold", 14)
    c.setFillColorRGB(0, 0, 0)
    c.drawString(inner_left, price_y, price_str)

    if on_sale:
        orig_str = f"${item.price:.2f}"
        price_w = c.stringWidth(price_str, "Helvetica-Bold", 14)
        c.setFont("Helvetica", 7.5)
        c.setFillColorRGB(0.4, 0.4, 0.4)
        orig_x = inner_left + price_w + 4
        c.drawString(orig_x, price_y + 2, orig_str)
        orig_w = c.stringWidth(orig_str, "Helvetica", 7.5)
        c.setStrokeColorRGB(0.4, 0.4, 0.4)
        c.setLineWidth(0.5)
        strike_y = price_y + 5
        c.line(orig_x, strike_y, orig_x + orig_w, strike_y)
        c.setFillColorRGB(0, 0, 0)

    barcode_val = item.barcode or ""
    if barcode_val:
        quiet_pad = 0.1 * inch
        avail_w = (inner_right - inner_left) - quiet_pad * 2

        bar_w = 1.3
        barcode_obj = code128.Code128(
            barcode_val,
            barHeight=0.45 * inch,
            barWidth=bar_w,
            humanReadable=False,
            quiet=False,
        )

        if barcode_obj.width > avail_w:
            bar_w = avail_w / barcode_obj.width * bar_w
            bar_w = max(bar_w, 0.55)
            barcode_obj = code128.Code128(
                barcode_val,
                barHeight=0.42 * inch,
                barWidth=bar_w,
                humanReadable=False,
                quiet=False,
            )

        barcode_w = barcode_obj.width
        barcode_x = (w - barcode_w) / 2
        barcode_y = margin + 11
        barcode_obj.drawOn(c, barcode_x, barcode_y)

        c.setFont("Helvetica", 6)
        c.drawCentredString(w / 2, margin + 4, barcode_val)


def generate_dymo_xml(item) -> str:
    from app.config import settings
    import xml.sax.saxutils as saxutils

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
    if on_sale:
        price_str += saxutils.escape(f"  (was ${item.price:.2f})")
    name_str = saxutils.escape((item.name or "")[:35])
    barcode_str = saxutils.escape(item.barcode or "")
    booth_str = saxutils.escape(f"Booth {booth_number}") if booth_number else ""

    if label_size == "30252":
        paper_name = "30252 Address"
        lw = 5040
        lh = 1620
    else:
        paper_name = "30336 1 in x 2-1/8 in"
        lw = 3060
        lh = 1440

    m = 60
    usable_w = lw - (m * 2)

    name_y = lh - m - 10
    name_h = int(lh * 0.18)
    price_w = int(usable_w * 0.55)
    booth_w = usable_w - price_w - 20
    price_y = name_y - name_h - 5
    price_h = int(lh * 0.16)
    barcode_h = lh - m - (name_h + price_h + 30) - m
    barcode_h = max(barcode_h, int(lh * 0.42))
    barcode_y = m

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DieCutLabel Version="8.0" Units="twips" MediaType="Default">
  <PaperOrientation>Landscape</PaperOrientation>
  <Id>Address</Id>
  <PaperName>{paper_name}</PaperName>
  <DrawCommands/>
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
            <Font Family="Arial" Size="14" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
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
  </ObjectInfo>
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
            <Font Family="Arial" Size="14" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
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
            <Font Family="Arial" Size="10" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
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
      <Type>Code128Auto</Type>
      <Size>Large</Size>
      <TextPosition>Bottom</TextPosition>
      <TextFont Family="Arial" Size="7" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
      <CheckSumFont Family="Arial" Size="7" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
      <TextEmbedding>None</TextEmbedding>
      <ECLevel>0</ECLevel>
      <HorizontalAlignment>Center</HorizontalAlignment>
      <QuietZonesPadding Left="0" Top="0" Right="0" Bottom="0"/>
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

    xml += """
</DieCutLabel>"""
    return xml
