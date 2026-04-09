import datetime
import xml.sax.saxutils as saxutils


def generate_dymo_xml(item) -> str:
    """Generate Dymo XML for a 30347 (1" x 1.5") label using native Dymo objects.

    Uses Code128Auto BarcodeObject so the printer firmware renders the barcode
    at full thermal resolution — far better quality than pre-rendered images.
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

    price_str = saxutils.escape(f"${active_price:.2f}")
    raw_barcode = item.barcode or ""
    barcode_str = saxutils.escape(raw_barcode)
    booth_str = saxutils.escape(f"B{booth_number}") if booth_number else ""

    # 30347 label: 1" wide x 1.5" tall = 1440 x 2160 twips
    # Portrait orientation: the label feeds long-edge first
    # Layout (rotated 90° so text reads correctly when label is on item):
    #   Left strip: barcode + barcode text
    #   Center: booth number
    #   Right strip: price (large)
    m = 44  # margin in twips

    # Barcode zone — left third of label
    barcode_x = m
    barcode_y = m
    barcode_w = 420
    barcode_h = 2160 - (m * 2)

    # Barcode text — narrow column right of barcode
    barcode_text_x = barcode_x + barcode_w + 8
    barcode_text_y = m
    barcode_text_w = 80
    barcode_text_h = barcode_h

    # Booth number — center area
    booth_x = barcode_text_x + barcode_text_w + 16
    booth_y = m
    booth_w = 280
    booth_h = barcode_h

    # Price — right strip, large
    price_x = 1440 - 380
    price_y = m
    price_w = 380 - m
    price_h = barcode_h

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DieCutLabel Version="8.0" Units="twips" MediaType="Default">
  <PaperOrientation>Portrait</PaperOrientation>
  <Id>Address</Id>
  <PaperName>30347 1 in x 1-1/2 in</PaperName>
  <DrawCommands/>
"""

    # Price object — large, right side
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
      <HorizontalAlignment>Center</HorizontalAlignment>
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
    <Bounds X="{price_x}" Y="{price_y}" Width="{price_w}" Height="{price_h}"/>
  </ObjectInfo>"""

    # Booth number — center
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
      <HorizontalAlignment>Center</HorizontalAlignment>
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
    <Bounds X="{booth_x}" Y="{booth_y}" Width="{booth_w}" Height="{booth_h}"/>
  </ObjectInfo>"""

    # Barcode — native Code128Auto rendered by printer firmware
    if barcode_str:
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
      <Size>Small</Size>
      <TextPosition>None</TextPosition>
      <TextFont Family="Arial" Size="6" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
      <CheckSumFont Family="Arial" Size="6" Bold="False" Italic="False" Underline="False" StrikeOut="False"/>
      <TextEmbedding>None</TextEmbedding>
      <ECLevel>0</ECLevel>
      <HorizontalAlignment>Center</HorizontalAlignment>
      <QuietZonesPadding Left="200" Top="0" Right="200" Bottom="0"/>
    </BarcodeObject>
    <Bounds X="{barcode_x}" Y="{barcode_y}" Width="{barcode_w}" Height="{barcode_h}"/>
  </ObjectInfo>"""

    # Barcode text — human-readable SKU next to barcode
    if barcode_str:
        xml += f"""
  <ObjectInfo>
    <TextObject>
      <Name>BARCODE_TEXT</Name>
      <ForeColor Alpha="255" Red="0" Green="0" Blue="0"/>
      <BackColor Alpha="0" Red="255" Green="255" Blue="255"/>
      <LinkedObjectName></LinkedObjectName>
      <Rotation>Rotation90</Rotation>
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
            <Font Family="Arial" Size="7" Bold="True" Italic="False" Underline="False" StrikeOut="False"/>
          </Attributes>
        </Element>
      </StyledText>
    </TextObject>
    <Bounds X="{barcode_text_x}" Y="{barcode_text_y}" Width="{barcode_text_w}" Height="{barcode_text_h}"/>
  </ObjectInfo>"""

    xml += """
</DieCutLabel>"""
    return xml
