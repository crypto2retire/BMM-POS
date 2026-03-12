import io
from decimal import Decimal
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
    margin = 0.08 * inch
    w = LABEL_WIDTH
    h = LABEL_HEIGHT

    name = item.name[:28] if item.name else ""
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, h - margin - 10, name)

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
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, h - margin - 26, price_str)

    if booth_number:
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(w - margin, h - margin - 10, f"Booth {booth_number}")

    barcode_obj = code128.Code128(item.barcode, barHeight=0.38 * inch, barWidth=1.0)
    barcode_w = barcode_obj.width
    barcode_x = (w - barcode_w) / 2
    barcode_obj.drawOn(c, barcode_x, margin + 8)

    c.setFont("Helvetica", 7)
    c.drawCentredString(w / 2, margin + 1, item.barcode)


def generate_dymo_xml(item) -> str:
    from app.config import settings

    label_size = settings.dymo_label_size

    booth_number = ""
    vendor = getattr(item, "vendor", None)
    if vendor:
        booth_number = getattr(vendor, "booth_number", "") or ""

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
    name_str = (item.name or "")[:35]
    barcode_str = item.barcode or ""
    booth_str = f"Booth: {booth_number}" if booth_number else ""
    price_booth = f"{price_str}  {booth_str}".strip()

    if label_size == "30252":
        paper_name = "30252 Address"
        lw = 5040
        lh = 1620
    else:
        paper_name = "30336 1 in x 2-1/8 in"
        lw = 3060
        lh = 1440

    m = 50
    row1_y = lh - m - int(lh * 0.28)
    row1_h = int(lh * 0.32)
    row2_y = lh - m - int(lh * 0.58)
    row2_h = int(lh * 0.28)
    row3_y = m
    row3_h = int(lh * 0.28)
    usable_w = lw - (m * 2)

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
      <DYMOPoint><X>{m}</X><Y>{row1_y}</Y></DYMOPoint>
      <Size><Width>{usable_w}</Width><Height>{row1_h}</Height></Size>
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
          <String>{price_booth}</String>
          <Attributes>
            <Font Family="Arial" Size="12" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <ObjectLayout>
      <DYMOPoint><X>{m}</X><Y>{row2_y}</Y></DYMOPoint>
      <Size><Width>{usable_w}</Width><Height>{row2_h}</Height></Size>
      <ZOrder>1</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>
  <ObjectInfo>
    <TextObject>
      <Name>BARCODE</Name>
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
            <Font Family="Courier New" Size="10" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <ObjectLayout>
      <DYMOPoint><X>{m}</X><Y>{row3_y}</Y></DYMOPoint>
      <Size><Width>{usable_w}</Width><Height>{row3_h}</Height></Size>
      <ZOrder>2</ZOrder>
      <AlternateColors>False</AlternateColors>
      <BorderStyle>SolidLine</BorderStyle>
      <BorderColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BorderThickness>0</BorderThickness>
    </ObjectLayout>
  </ObjectInfo>
</DieCutLabel>"""
    return xml
