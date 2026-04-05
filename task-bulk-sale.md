# Task: Add Bulk "Apply Sale" Feature for Vendor Items

## Overview
Vendors need to select items (using existing checkboxes or "Select All") and apply a sale to all of them at once — percentage off + date range. This is for scenarios like "everything in the booth is 20% off this weekend."

The existing checkbox selection system and "Select All" button already work. We just need a new "Apply Sale" button in the batch actions bar and a modal + backend endpoint.

---

## PART 1: Backend — New bulk sale endpoint

### File: `app/routers/items.py`

Add a new endpoint after the existing `/bulk-status` endpoint:

```python
@router.post("/bulk-sale")
async def bulk_apply_sale(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    """Apply a percentage-off sale to multiple items at once."""
    item_ids = body.get("item_ids", [])
    percent_off = body.get("percent_off")
    sale_start = body.get("sale_start")
    sale_end = body.get("sale_end")

    if not item_ids:
        raise HTTPException(status_code=400, detail="No items selected")
    if not percent_off or float(percent_off) <= 0 or float(percent_off) > 100:
        raise HTTPException(status_code=400, detail="Percent off must be between 1 and 100")
    if not sale_start or not sale_end:
        raise HTTPException(status_code=400, detail="Sale start and end dates are required")
    if sale_end < sale_start:
        raise HTTPException(status_code=400, detail="Sale end must be after sale start")

    percent = Decimal(str(percent_off)) / Decimal("100")

    # Fetch items — vendors can only modify their own
    query = select(Item).where(Item.id.in_(item_ids))
    if current_user.role == "vendor":
        query = query.where(Item.vendor_id == current_user.id)

    result = await db.execute(query)
    items = result.scalars().all()

    updated = 0
    for item in items:
        original_price = Decimal(str(item.price))
        sale_price = (original_price * (Decimal("1") - percent)).quantize(Decimal("0.01"))
        item.sale_price = sale_price
        item.sale_start = sale_start
        item.sale_end = sale_end
        updated += 1

    await db.commit()
    return {"updated": updated, "percent_off": float(percent_off), "sale_start": sale_start, "sale_end": sale_end}
```

Make sure `Decimal` is imported at the top of the file (it likely already is from other usage, but verify).

Also add a companion endpoint to clear sales in bulk:

```python
@router.post("/bulk-clear-sale")
async def bulk_clear_sale(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    """Remove sale pricing from multiple items at once."""
    item_ids = body.get("item_ids", [])
    if not item_ids:
        raise HTTPException(status_code=400, detail="No items selected")

    query = select(Item).where(Item.id.in_(item_ids))
    if current_user.role == "vendor":
        query = query.where(Item.vendor_id == current_user.id)

    result = await db.execute(query)
    items = result.scalars().all()

    updated = 0
    for item in items:
        item.sale_price = None
        item.sale_start = None
        item.sale_end = None
        updated += 1

    await db.commit()
    return {"cleared": updated}
```

---

## PART 2: Frontend — Batch actions bar + modal

### File: `frontend/vendor/items.html`

### Step 1 — Add "Apply Sale" and "Clear Sale" buttons to batch actions bar

Find the batch-actions-bar div (around line ~277). Add two new buttons after the existing ones, before the Clear button:

```html
<button class="btn btn-primary" onclick="openBulkSaleModal()" style="font-size:0.75rem; padding:0.4rem 1rem; background:#C9A96E; border-color:#C9A96E; color:#38383B">Apply Sale</button>
<button class="btn btn-outline" onclick="bulkClearSale()" style="font-size:0.72rem; padding:0.35rem 0.8rem; color:#F59E0B; border-color:rgba(245,158,11,0.3)">Clear Sale</button>
```

### Step 2 — Add bulk sale modal HTML

Add this modal HTML near the other modals (after the batch actions bar or near the end of the body):

```html
<div class="modal-overlay hidden" id="bulk-sale-modal">
    <div class="modal" style="max-width:400px">
        <div class="modal-header">
            <h3 class="modal-title">Apply Sale to Selected Items</h3>
            <button class="modal-close" onclick="closeBulkSaleModal()">✕</button>
        </div>
        <div class="modal-body">
            <div id="bulk-sale-alert"></div>
            <p style="font-size:0.82rem;color:var(--text-light);margin-bottom:1rem">
                <strong id="bulk-sale-count">0</strong> items selected — each item's sale price will be calculated from its regular price.
            </p>
            <div class="form-group" style="margin-bottom:1rem">
                <label class="form-label">Percent Off *</label>
                <div style="display:flex;align-items:center;gap:8px">
                    <input class="form-control" type="number" id="bulk-sale-percent"
                        min="1" max="100" step="1" placeholder="e.g. 20" inputmode="numeric"
                        style="max-width:120px">
                    <span style="font-size:1rem;color:var(--text-light)">% off</span>
                </div>
            </div>
            <div style="display:flex;gap:1rem">
                <div class="form-group" style="flex:1">
                    <label class="form-label">Sale Start *</label>
                    <input class="form-control" type="date" id="bulk-sale-start">
                </div>
                <div class="form-group" style="flex:1">
                    <label class="form-label">Sale End *</label>
                    <input class="form-control" type="date" id="bulk-sale-end">
                </div>
            </div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-secondary" onclick="closeBulkSaleModal()">Cancel</button>
            <button class="btn btn-primary" onclick="submitBulkSale()" id="bulk-sale-submit"
                style="background:#C9A96E;border-color:#C9A96E;color:#38383B">Apply Sale</button>
        </div>
    </div>
</div>
```

### Step 3 — Add JavaScript functions

Add these functions near the existing bulk operations (around line ~1504 near `bulkSetStatus`):

```javascript
function openBulkSaleModal() {
    const count = selectedItemIds.size;
    if (count === 0) { showAlert('alert-container', 'No items selected.', 'warning'); return; }
    document.getElementById('bulk-sale-count').textContent = count;
    document.getElementById('bulk-sale-percent').value = '';
    document.getElementById('bulk-sale-start').value = '';
    document.getElementById('bulk-sale-end').value = '';
    document.getElementById('bulk-sale-alert').innerHTML = '';
    document.getElementById('bulk-sale-modal').classList.remove('hidden');
    document.getElementById('bulk-sale-percent').focus();
}

function closeBulkSaleModal() {
    document.getElementById('bulk-sale-modal').classList.add('hidden');
}

async function submitBulkSale() {
    const percent = parseFloat(document.getElementById('bulk-sale-percent').value);
    const start = document.getElementById('bulk-sale-start').value;
    const end = document.getElementById('bulk-sale-end').value;
    const alertEl = document.getElementById('bulk-sale-alert');

    if (!percent || percent <= 0 || percent > 100) {
        showAlert('bulk-sale-alert', 'Enter a valid percentage (1-100).', 'error');
        return;
    }
    if (!start || !end) {
        showAlert('bulk-sale-alert', 'Both start and end dates are required.', 'error');
        return;
    }
    if (end < start) {
        showAlert('bulk-sale-alert', 'End date must be after start date.', 'error');
        return;
    }

    const btn = document.getElementById('bulk-sale-submit');
    btn.disabled = true;
    btn.textContent = 'Applying…';

    try {
        const ids = Array.from(selectedItemIds);
        const resp = await apiPost('/api/v1/items/bulk-sale', {
            item_ids: ids,
            percent_off: percent,
            sale_start: start,
            sale_end: end,
        });
        closeBulkSaleModal();
        showAlert('alert-container', `Sale applied to ${resp.updated} items (${percent}% off, ${start} to ${end}).`, 'success');
        selectedItemIds.clear();
        updateSelectionUI();
        await loadItems();
    } catch (err) {
        showAlert('bulk-sale-alert', err.message || 'Failed to apply sale.', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Apply Sale';
    }
}

async function bulkClearSale() {
    const count = selectedItemIds.size;
    if (count === 0) { showAlert('alert-container', 'No items selected.', 'warning'); return; }
    if (!confirm(`Clear sale pricing from ${count} item(s)?`)) return;

    try {
        const ids = Array.from(selectedItemIds);
        const resp = await apiPost('/api/v1/items/bulk-clear-sale', { item_ids: ids });
        showAlert('alert-container', `Sale cleared from ${resp.cleared} items.`, 'success');
        selectedItemIds.clear();
        updateSelectionUI();
        await loadItems();
    } catch (err) {
        showAlert('alert-container', err.message || 'Failed to clear sales.', 'error');
    }
}
```

Note: `apiPost` should already exist as a helper. If the codebase uses `apiFetch('POST', ...)` instead, use that pattern. Check what other bulk functions use.

---

## Design notes
- "Apply Sale" button uses gold background (#C9A96E) to stand out as the key action
- "Clear Sale" button uses outline style with warning orange color
- Modal follows existing modal patterns in the codebase (modal-overlay, modal, modal-header, modal-body, modal-footer classes)
- Both buttons only appear in the batch actions bar (which only shows when items are selected)

## Test
1. Select a few items with checkboxes → "Apply Sale" button appears in batch bar
2. Click "Apply Sale" → modal shows with item count, percent input, date range
3. Enter 20%, set dates → click Apply → items update with sale prices (each item's price × 0.80)
4. Verify sale prices appear in the item list
5. Select All → Apply Sale → works for all items
6. Select items on sale → "Clear Sale" → sale pricing removed
7. Vendor can only modify their own items (non-admin)
8. Commit and push to main
