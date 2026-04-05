# Task: Inventory Verification — Part 3: View & Manage Unverified Items

Add the ability to view unverified Ricochet items per vendor and archive them individually or per-vendor. This closes the gap where unverified items (likely sold) don't appear in the Review Queue and vendors can't reach COMPLETE status.

**Prerequisite:** Parts 1 and 2 must be deployed.

---

## Step 1: Add backend endpoint for listing unverified items

File: `app/routers/inventory_verify.py`

Add this new endpoint (place it after the `reset` endpoint and before `archive-unverified`):

```python
@router.get("/unverified/{vendor_id}")
async def list_unverified_items(
    vendor_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin", "cashier")),
):
    """List active Ricochet items for a vendor that have NOT been verified."""
    # Get vendor name
    vendor_result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = vendor_result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Count total
    count_result = await db.execute(
        select(func.count(Item.id)).where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
    )
    total = count_result.scalar() or 0

    # Get items
    result = await db.execute(
        select(Item)
        .where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
        .order_by(Item.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = result.scalars().all()

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor.name,
        "items": [
            {
                "id": i.id,
                "sku": i.sku,
                "barcode": i.barcode,
                "name": i.name,
                "price": float(i.price),
                "quantity": i.quantity,
                "category": i.category,
                "created_at": i.created_at.isoformat() if i.created_at else None,
            }
            for i in items
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total > 0 else 1,
    }
```

Also add an endpoint to archive a single vendor's unverified items:

```python
@router.post("/archive-vendor/{vendor_id}")
async def archive_vendor_unverified(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin")),
):
    """Archive unverified Ricochet items for a single vendor. 30-day hold."""
    expires = datetime.utcnow() + timedelta(days=30)

    count_result = await db.execute(
        select(func.count(Item.id)).where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
    )
    count = count_result.scalar() or 0

    if count == 0:
        return {"archived": 0, "detail": "No unverified items for this vendor."}

    await db.execute(
        update(Item)
        .where(
            Item.vendor_id == vendor_id,
            Item.status == "active",
            Item.verified_at.is_(None),
            _ricochet_filter(),
        )
        .values(
            status="pending_delete",
            archive_expires_at=expires,
        )
    )
    await db.commit()

    return {
        "archived": count,
        "expires_at": expires.isoformat(),
        "detail": f"Archived {count} unverified items. Held for 30 days.",
    }
```

And add an endpoint to manually mark a single item as verified (keep it):

```python
@router.post("/verify-item/{item_id}")
async def manually_verify_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_role("admin", "cashier")),
):
    """Manually mark a single item as verified (keep it active)."""
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.verified_at = datetime.utcnow()
    await db.commit()

    return {"detail": f"Item '{item.name}' marked as verified."}
```

---

## Step 2: Update the frontend — add unverified items modal to Progress tab

File: `frontend/admin/inventory-verify.html`

### 2a: Add CSS for the modal

Add this inside the `<style>` block, before the closing `</style>`:

```css
        /* ── Unverified modal ──────────────────────────── */
        .modal-overlay {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.6);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }
        .modal-overlay.open {
            display: flex;
        }
        .modal-box {
            background: var(--bg);
            border: 1px solid var(--warm-border);
            width: calc(100% - 2rem);
            max-width: 800px;
            max-height: 85vh;
            overflow-y: auto;
            padding: 1.5rem;
        }
        .modal-box h3 {
            font-family: 'EB Garamond', Georgia, serif;
            font-size: 1.25rem;
            font-weight: 500;
            color: var(--text);
            margin-bottom: 0.5rem;
        }
        .modal-box .modal-sub {
            font-size: 0.78rem;
            color: var(--text-light);
            margin-bottom: 1rem;
        }
        .modal-close {
            float: right;
            background: none;
            border: none;
            color: var(--text-light);
            font-size: 1.25rem;
            cursor: pointer;
            padding: 0.25rem 0.5rem;
            min-height: 44px;
            min-width: 44px;
        }
        .modal-close:hover { color: var(--text); }
        .modal-actions {
            display: flex;
            gap: 0.75rem;
            margin-top: 1rem;
            flex-wrap: wrap;
        }

        @media (max-width: 767px) {
            .modal-box { padding: 1rem; }
        }
```

### 2b: Add the modal HTML

Add this just before the closing `</div>` of `main-content` (right before the `<script>` tag):

```html
    <!-- Unverified items modal -->
    <div class="modal-overlay" id="unverified-modal">
        <div class="modal-box">
            <button class="modal-close" onclick="closeUnverifiedModal()">&times;</button>
            <h3>Unverified Items — <span id="unverified-vendor-name"></span></h3>
            <p class="modal-sub">These Ricochet-imported items were NOT found in the vendor's CSV export. They are likely sold items.</p>
            <div class="vendor-table-wrap">
                <table class="verify-table" id="unverified-table">
                    <thead>
                        <tr>
                            <th>SKU</th>
                            <th>Barcode</th>
                            <th>Name</th>
                            <th>Price</th>
                            <th>Qty</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="unverified-tbody"></tbody>
                </table>
            </div>
            <div class="pagination-bar" id="unverified-pagination" style="display:none">
                <div>
                    <button onclick="unverifiedPage(1)">First</button>
                    <button onclick="unverifiedPage(unvState.page - 1)">Prev</button>
                </div>
                <span id="unverified-page-info">Page 1 of 1</span>
                <div>
                    <button onclick="unverifiedPage(unvState.page + 1)">Next</button>
                    <button onclick="unverifiedPage(unvState.totalPages)">Last</button>
                </div>
            </div>
            <div class="modal-actions">
                <button class="btn-warning" id="archive-vendor-btn" onclick="archiveVendorUnverified()">
                    &#9888; Archive All Unverified for This Vendor
                </button>
                <button class="btn-sm" onclick="closeUnverifiedModal()">Close</button>
            </div>
        </div>
    </div>
```

### 2c: Update the Progress table to add a "View" button

In the JavaScript, find the `renderProgress` function. In the Actions `<td>`, change the Reset button line to include a View button before it:

Find this in `renderProgress`:
```javascript
            '<td>' +
                '<button class="btn-sm" onclick="resetVendor(' + v.id + ', \'' + esc(v.name).replace(/'/g, "\\'") + '\')" title="Reset verification">Reset</button>' +
            '</td>' +
```

Replace with:
```javascript
            '<td style="white-space:nowrap">' +
                (v.unverified_items > 0
                    ? '<button class="btn-sm" onclick="showUnverified(' + v.id + ', \'' + esc(v.name).replace(/'/g, "\\'") + '\')" title="View unverified items" style="color:#fbbf24; margin-right:4px">' + v.unverified_items + ' unverified</button> '
                    : '') +
                '<button class="btn-sm" onclick="resetVendor(' + v.id + ', \'' + esc(v.name).replace(/'/g, "\\'") + '\')" title="Reset verification">Reset</button>' +
            '</td>' +
```

### 2d: Add the JavaScript functions for the modal

Add these functions to the `<script>` block, before the `// ── Init` section:

```javascript
// ── Unverified items modal ─────────────────────────
var unvState = { vendorId: null, vendorName: '', page: 1, totalPages: 1 };

async function showUnverified(vendorId, vendorName) {
    unvState.vendorId = vendorId;
    unvState.vendorName = vendorName;
    unvState.page = 1;
    document.getElementById('unverified-vendor-name').textContent = vendorName;
    document.getElementById('unverified-modal').classList.add('open');
    await loadUnverifiedItems();
}

function closeUnverifiedModal() {
    document.getElementById('unverified-modal').classList.remove('open');
}

async function loadUnverifiedItems() {
    var url = API + '/inventory-verify/unverified/' + unvState.vendorId + '?page=' + unvState.page + '&per_page=50';
    try {
        var res = await fetch(url, { headers: headers });
        if (!res.ok) throw new Error('Failed to load unverified items');
        var data = await res.json();

        unvState.totalPages = data.total_pages;
        var tbody = document.getElementById('unverified-tbody');

        if (!data.items.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:1.5rem; color:var(--text-light)">No unverified items</td></tr>';
            document.getElementById('unverified-pagination').style.display = 'none';
            document.getElementById('archive-vendor-btn').style.display = 'none';
            return;
        }

        document.getElementById('archive-vendor-btn').style.display = '';

        tbody.innerHTML = data.items.map(function(i) {
            return '<tr>' +
                '<td style="font-size:0.72rem">' + esc(i.sku) + '</td>' +
                '<td style="font-size:0.72rem; font-family:monospace">' + esc(i.barcode) + '</td>' +
                '<td>' + esc(i.name) + '</td>' +
                '<td>$' + i.price.toFixed(2) + '</td>' +
                '<td>' + i.quantity + '</td>' +
                '<td style="white-space:nowrap">' +
                    '<button class="btn-sm approve" onclick="keepItem(' + i.id + ', this)" title="Keep (mark verified)">Keep</button> ' +
                '</td>' +
            '</tr>';
        }).join('');

        if (data.total_pages > 1) {
            document.getElementById('unverified-pagination').style.display = 'flex';
            document.getElementById('unverified-page-info').textContent = 'Page ' + data.page + ' of ' + data.total_pages + ' (' + data.total + ' items)';
        } else {
            document.getElementById('unverified-pagination').style.display = 'none';
        }

    } catch (e) {
        showAlert('Error loading unverified items: ' + e.message, 'error');
    }
}

function unverifiedPage(p) {
    if (p < 1 || p > unvState.totalPages) return;
    unvState.page = p;
    loadUnverifiedItems();
}

async function keepItem(itemId, btn) {
    btn.disabled = true;
    try {
        var res = await fetch(API + '/inventory-verify/verify-item/' + itemId, {
            method: 'POST',
            headers: headers,
        });
        if (!res.ok) throw new Error('Failed to verify item');
        btn.closest('tr').remove();
        loadStatus();
    } catch (e) {
        showAlert('Error: ' + e.message, 'error');
        btn.disabled = false;
    }
}

async function archiveVendorUnverified() {
    if (!confirm('Archive all unverified items for "' + unvState.vendorName + '"?\n\nThey will be held for 30 days before permanent deletion.')) return;

    try {
        var res = await fetch(API + '/inventory-verify/archive-vendor/' + unvState.vendorId, {
            method: 'POST',
            headers: headers,
        });
        var data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Archive failed');
        showAlert('Archived ' + data.archived + ' items for ' + unvState.vendorName, 'success');
        closeUnverifiedModal();
        loadStatus();
    } catch (e) {
        showAlert('Error: ' + e.message, 'error');
    }
}
```

---

## Summary

**Backend — 3 new endpoints:**

| Method | Endpoint | Roles | Purpose |
|--------|----------|-------|---------|
| GET | `/api/v1/inventory-verify/unverified/{vendor_id}` | admin, cashier | List unverified Ricochet items for a vendor |
| POST | `/api/v1/inventory-verify/archive-vendor/{vendor_id}` | admin | Archive one vendor's unverified items (30-day hold) |
| POST | `/api/v1/inventory-verify/verify-item/{item_id}` | admin, cashier | Manually mark a single item as verified (keep it) |

**Frontend changes:**
- Progress tab: each vendor with unverified items gets a yellow "X unverified" button
- Clicking it opens a modal showing the unverified items with name, SKU, barcode, price
- Each item has a "Keep" button to manually mark it verified (in case it's actually still in stock)
- Bottom of modal has "Archive All Unverified for This Vendor" button
- Modal is paginated for vendors with many unverified items

Commit and push when done.
