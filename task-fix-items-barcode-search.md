# Task: Fix Items Page Search to Match Barcodes

## Problem
Scanning a barcode on the vendor items page (`frontend/vendor/items.html`) doesn't find the item. The search only checks `name` and `sku` but not `barcode`. Items imported via bulk import have barcodes that work at the POS but can't be found on the items management page.

## File to edit
`frontend/vendor/items.html`

## Fix 1 — Add barcode to getFilteredItems()

Find `getFilteredItems()` (around line ~1592):

```javascript
function getFilteredItems() {
    if (!searchTerm) return allItems.slice();
    return allItems.filter(item => {
        const name = (item.name || '').toLowerCase();
        const sku = (item.sku || '').toLowerCase();
        return name.includes(searchTerm) || sku.includes(searchTerm);
    });
}
```

Replace with:

```javascript
function getFilteredItems() {
    if (!searchTerm) return allItems.slice();
    return allItems.filter(item => {
        const name = (item.name || '').toLowerCase();
        const sku = (item.sku || '').toLowerCase();
        const barcode = (item.barcode || '').toLowerCase();
        return name.includes(searchTerm) || sku.includes(searchTerm) || barcode.includes(searchTerm);
    });
}
```

## Fix 2 — Update search placeholder

Find the search input (around line ~317):

```html
placeholder="Search by name or SKU…"
```

Change to:

```html
placeholder="Search by name, SKU, or barcode…"
```

## Test
1. Open vendor items page
2. Scan a barcode into the search box — item should appear
3. Type a partial barcode — matching items should filter
4. Name and SKU search still work as before
5. Commit and push to main
