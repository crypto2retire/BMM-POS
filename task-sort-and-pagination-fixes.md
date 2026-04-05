# Task: Fix Sort Default + Add 100 to Pagination

Two small fixes across the items and vendors pages.

---

## FIX 1: Items not showing newest first

### Problem
Despite `sortDirection = 'desc'` and `sortColumn = 'created_at'` being the defaults, items are appearing oldest-first. The frontend sort IS being called (`getSortedItems` in `displayItems`), so the issue is likely:

1. Items that were bulk-imported may have similar/identical `created_at` timestamps
2. The API returns items without an `ORDER BY`, so the initial array order from PostgreSQL is undefined

### Fix — Two changes:

**File: `app/routers/items.py`**

In the `list_items` function (around line ~90-93), add an `order_by` before executing the query:

```python
query = query.order_by(Item.created_at.desc())
```

Add this line right before `if limit:` (around line ~90). This ensures the API always returns newest first regardless of what the frontend does.

**File: `frontend/vendor/items.html`**

Double-check that the `displayItems()` function calls `getSortedItems(filtered)` BEFORE slicing for pagination. The sort must happen before the page slice. Look at `displayItems()` around line ~1570 — verify the flow is:

1. Filter items
2. Sort items (getSortedItems)
3. THEN slice for current page

If the sort is happening after the slice, that would explain why only each page is sorted, not the full list. Fix the order if needed.

Also verify that on page load, the sort-order dropdown value is being set correctly. Around line ~1891 there should be:
```javascript
document.getElementById('sort-order').value = sortDirection;
```

If this line doesn't exist or is setting the wrong value, add/fix it.

---

## FIX 2: Add 100 per page option

### File: `frontend/vendor/items.html`

Find the page-size-select dropdown (around line ~319-323). Add the 100 option:

```html
<option value="10">10 per page</option>
<option value="25">25 per page</option>
<option value="50">50 per page</option>
<option value="100">100 per page</option>
```

### File: `frontend/admin/vendors.html`

Find the vendor-page-size dropdown (around line ~288-292). Add the 100 option:

```html
<option value="10">10 per page</option>
<option value="25">25 per page</option>
<option value="50">50 per page</option>
<option value="100">100 per page</option>
```

---

## Test
1. Vendor items page: newest items appear at top by default on page load
2. Switching to "Oldest First" shows oldest at top, "Newest First" goes back
3. Both items and vendors pages show 10/25/50/100 options in the page size dropdown
4. Selecting 100 shows up to 100 items per page
5. Commit and push to main
