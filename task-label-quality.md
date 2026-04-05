# Task: Fix Label Barcode Quality — Switch from Code39 to Code128

Barcodes on printed labels are blurry and don't always scan. The root cause is using Code39 format, which requires ~78 modules for a 6-character code. Code128 only needs ~46 modules for the same data — nearly 40% fewer bars. This means wider bars, cleaner prints, and reliable scanning on small Dymo 1"x1.5" labels.

Three files need changes. All barcodes are 6-character alphanumeric codes.

---

## File 1: `app/services/labels.py` (PDF label generation)

### Change A — Switch import from code39 to code128

Find (line 6):

```python
from reportlab.graphics.barcode import code39
```

Replace with:

```python
from reportlab.graphics.barcode import code128
```

### Change B — Switch the probe barcode object

Find (around line 150-152):

```python
        probe = code39.Standard39(barcode_val, barHeight=10, barWidth=1.0,
                                   humanReadable=False, quiet=False, checksum=False)
        min_modules = probe.width
```

Replace with:

```python
        probe = code128.Code128(barcode_val, barHeight=10, barWidth=1.0,
                                humanReadable=False, quiet=False)
        min_modules = probe.width
```

### Change C — Switch the actual barcode object + add quiet zones

Find (around line 154-168):

```python
        raw_bar_w = avail_w / min_modules
        bar_w = max(math.floor(raw_bar_w / DOT), 1) * DOT

        barcode_obj = code39.Standard39(
            barcode_val,
            barHeight=bar_h,
            barWidth=bar_w,
            humanReadable=False,
            quiet=False,
            checksum=False,
        )

        barcode_w = barcode_obj.width
        barcode_x = _snap_down((w - barcode_w) / 2)
        barcode_obj.drawOn(c, barcode_x, barcode_y)
```

Replace with:

```python
        # Reserve 10x module width for quiet zones (5x each side)
        quiet_zone = 10 * DOT
        usable_w = avail_w - quiet_zone * 2

        raw_bar_w = usable_w / min_modules
        bar_w = max(math.floor(raw_bar_w / DOT), 1) * DOT

        barcode_obj = code128.Code128(
            barcode_val,
            barHeight=bar_h,
            barWidth=bar_w,
            humanReadable=False,
            quiet=False,
        )

        barcode_w = barcode_obj.width
        barcode_x = _snap_down((w - barcode_w) / 2)
        barcode_obj.drawOn(c, barcode_x, barcode_y)
```

### Change D — Switch Dymo XML barcode type

Find (around line 350):

```xml
      <Type>Code39</Type>
```

Replace with:

```xml
      <Type>Code128Auto</Type>
```

### Change E — Add quiet zones to Dymo barcode

Find (around line 358):

```xml
      <QuietZonesPadding Left="0" Top="0" Right="0" Bottom="0"/>
```

Replace with:

```xml
      <QuietZonesPadding Left="10" Top="0" Right="10" Bottom="0"/>
```

---

## File 2: `app/services/barcode.py` (barcode image generation)

### Change F — Switch image generation to Code128

Find (around line 35-42):

```python
def generate_barcode_image(barcode_value: str, output_path: str) -> str:
    import barcode
    from barcode.writer import ImageWriter

    code39 = barcode.get("code39", barcode_value, writer=ImageWriter(), add_checksum=False)
    filename = output_path.replace(".png", "")
    saved = code39.save(filename)
    return saved
```

Replace with:

```python
def generate_barcode_image(barcode_value: str, output_path: str) -> str:
    import barcode
    from barcode.writer import ImageWriter

    bc = barcode.get("code128", barcode_value, writer=ImageWriter())
    filename = output_path.replace(".png", "")
    saved = bc.save(filename)
    return saved
```

Note: Code128 doesn't use `add_checksum` — it has a mandatory built-in checksum.

---

## File 3: `frontend/vendor/items.html` (Dymo print function)

Check if the frontend Dymo print function specifies a barcode type. If it does, update it to match. If it just sends the item data and the backend handles barcode type (which it should from the XML), no change needed here.

---

## What This Fixes

| Problem | Before (Code39) | After (Code128) |
|---------|-----------------|-----------------|
| Modules for 6-char code | ~78 | ~46 |
| Bar width on 1" label | Very thin, blur-prone | ~40% wider |
| Quiet zones | None | 10-unit padding each side |
| Scanner reliability | Intermittent fails | Reliable reads |
| Dymo barcode type | Code39 | Code128Auto |

**Backward compatibility:** Existing barcodes (the 6-character alphanumeric values in the database) don't change. Only the visual encoding on the label changes. Any scanner that reads Code39 also reads Code128 — it's a more universal format.

No database changes needed. Commit and push when done.
