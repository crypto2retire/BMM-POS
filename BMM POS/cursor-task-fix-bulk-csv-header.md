# Cursor Task: Fix Bulk CSV Upload — Header Detection

## Problem

The `POST /inventory-verify/upload-bulk` endpoint fails with "CSV must have a 'SKU' column" because the Ricochet CSV export may or may not have a title row before the actual header row. The current skip logic only handles one specific case.

## Fix

### File: `app/routers/inventory_verify.py`

**Find** the header-skip block in `verify_bulk_inventory` (the `upload-bulk` endpoint):

```python
    lines = text.split("\n")
    if lines and not lines[0].strip().startswith("Product ID"):
        text = "\n".join(lines[1:])

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}
    if "sku" not in headers_lower:
        raise HTTPException(status_code=400, detail="CSV must have a 'SKU' column")
```

**Replace with:**

```python
    # Find the actual header row — skip any title/metadata rows before it
    lines = text.split("\n")
    header_idx = 0
    for i, line in enumerate(lines[:5]):  # Check first 5 lines
        if "SKU" in line and "Product ID" in line:
            header_idx = i
            break
    if header_idx > 0:
        text = "\n".join(lines[header_idx:])

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}
    if "sku" not in headers_lower:
        # Last resort: maybe the header row uses different casing or has extra whitespace
        # Try to find any field containing "sku"
        found_sku = False
        for h in reader.fieldnames:
            if "sku" in h.strip().lower():
                found_sku = True
                break
        if not found_sku:
            raise HTTPException(
                status_code=400,
                detail=f"CSV must have a 'SKU' column. Found columns: {', '.join(reader.fieldnames[:10])}"
            )
```

**Also apply the same fix to the per-vendor `verify_vendor_inventory` endpoint** — find its header detection (around line 131):

```python
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}

    if "sku" not in headers_lower:
        raise HTTPException(status_code=400, detail="CSV must have a 'SKU' column")
```

**Replace with:**

```python
    # Find the actual header row — skip any title/metadata rows before it
    lines = text.split("\n")
    header_idx = 0
    for i, line in enumerate(lines[:5]):
        if "SKU" in line and ("Product ID" in line or "Name" in line):
            header_idx = i
            break
    if header_idx > 0:
        text = "\n".join(lines[header_idx:])

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV has no headers")

    headers_lower = {h.strip().lower(): h.strip() for h in reader.fieldnames}

    if "sku" not in headers_lower:
        raise HTTPException(
            status_code=400,
            detail=f"CSV must have a 'SKU' column. Found columns: {', '.join(reader.fieldnames[:10])}"
        )
```

## Why This Fix Works

Instead of guessing whether line 1 is a title row, it searches the first 5 lines for the one containing both "SKU" and "Product ID" — that's the real header row. Everything before it gets skipped. If the header row is already line 1 (no title row), `header_idx` stays at 0 and nothing is skipped.

The improved error message also now shows what columns WERE found, making debugging much easier.

## Files Changed
- `app/routers/inventory_verify.py` — robust header detection in both upload endpoints

## Testing
1. Upload a Ricochet CSV with a title row (like `Products 2026-04-01T...`) — should work
2. Upload a CSV without a title row (headers on line 1) — should also work
3. Run `python3 -m py_compile app/routers/inventory_verify.py`
