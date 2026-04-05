# Task: Add Page Size Selector to Items and Vendors Pages

## Overview
Add a dropdown to control how many items/vendors show per page (10, 25, 50). Both the vendor items page and admin vendors page need this.

---

## FILE 1: `frontend/vendor/items.html` (Items Page)

The items page ALREADY has pagination with Prev/Next buttons and a `PAGE_SIZE` constant set to 50. The change is small: make `PAGE_SIZE` a variable and add a dropdown to change it.

### Step 1 — Change PAGE_SIZE from const to let

Around line ~620, change:
```javascript
const PAGE_SIZE = 50;
```
to:
```javascript
let pageSize = parseInt(localStorage.getItem('bmm_items_pageSize')) || 25;
```

Default to 25 instead of 50 — it's a better starting point.

### Step 2 — Replace all references to PAGE_SIZE with pageSize

There are references around lines ~1695-1698. Change `PAGE_SIZE` to `pageSize` everywhere it appears (should be about 3 occurrences).

### Step 3 — Add page size dropdown in the toolbar

In the `.items-toolbar` div (around line ~316), add this after the search input and before the sort/view controls:

```html
<select id="page-size-select" onchange="changePageSize(this.value)"
    style="padding:0.4rem 0.6rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text-light); font-size:0.72rem; font-family:'Roboto',sans-serif; cursor:pointer">
    <option value="10">10 per page</option>
    <option value="25">25 per page</option>
    <option value="50">50 per page</option>
</select>
```

### Step 4 — Add changePageSize function

Near the `changePage()` function (around line ~1772):

```javascript
function changePageSize(size) {
    pageSize = parseInt(size);
    localStorage.setItem('bmm_items_pageSize', pageSize);
    currentPage = 1;
    displayItems();
}
```

### Step 5 — Set the dropdown's selected value on init

In the `init()` or page load area, after the DOM is ready, add:
```javascript
document.getElementById('page-size-select').value = pageSize;
```

### Step 6 — Also show pagination bar in grid view

Currently the pagination bar is only rendered inside `renderListView`. Check if `renderGridView` (the card/grid layout) also has pagination. If not, add the same pagination bar HTML after the grid cards so both views have Prev/Next and the item count display.

---

## FILE 2: `frontend/admin/vendors.html` (Vendors Page)

This page has NO pagination at all — `renderGrid()` renders all vendors into the table and cards at once. Need to add pagination from scratch.

### Step 1 — Add state variables

Near the top of the script section (around line ~543 near `let allVendors = [];`):

```javascript
let vendorPage = 1;
let vendorPageSize = parseInt(localStorage.getItem('bmm_vendors_pageSize')) || 25;
```

### Step 2 — Add page size dropdown to the page

Find the search input area in the HTML. Add a page size dropdown next to it, styled to match the BMM-POS dark editorial look:

```html
<select id="vendor-page-size" onchange="changeVendorPageSize(this.value)"
    style="padding:0.4rem 0.6rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text-light); font-size:0.72rem; font-family:'Roboto',sans-serif; cursor:pointer">
    <option value="10">10 per page</option>
    <option value="25">25 per page</option>
    <option value="50">50 per page</option>
</select>
```

### Step 3 — Add pagination to renderGrid()

Modify the `renderGrid(vendors)` function to slice the array by page:

```javascript
function renderGrid(vendors) {
    const tbody = document.getElementById('vendors-table-body');
    const cards = document.getElementById('vendor-cards');

    if (vendors.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No vendors found.</td></tr>';
        cards.innerHTML = '<div style="color:#A8A6A1;padding:1rem;text-align:center">No vendors found.</div>';
        // Clear any existing pagination
        const existingPag = document.getElementById('vendor-pagination');
        if (existingPag) existingPag.innerHTML = '';
        return;
    }

    const total = vendors.length;
    const totalPages = Math.ceil(total / vendorPageSize);
    if (vendorPage > totalPages) vendorPage = totalPages;
    const start = (vendorPage - 1) * vendorPageSize;
    const end = Math.min(start + vendorPageSize, total);
    const pageVendors = vendors.slice(start, end);

    // ... existing render code, but use pageVendors instead of vendors ...

    // Add pagination bar after the table/cards
    // Either insert into a dedicated div or append to the container
}
```

### Step 4 — Add pagination bar HTML

After the table, add a pagination bar container in the HTML:
```html
<div id="vendor-pagination" class="pagination-bar"></div>
```

Update `renderGrid` to populate it:
```javascript
const pagDiv = document.getElementById('vendor-pagination');
if (pagDiv) {
    pagDiv.innerHTML = `
        <span>Showing ${start + 1}–${end} of ${total} vendors</span>
        <div style="display:flex;gap:6px">
            <button onclick="changeVendorPage(-1)" ${vendorPage <= 1 ? 'disabled' : ''}>Prev</button>
            <button onclick="changeVendorPage(1)" ${vendorPage >= totalPages ? 'disabled' : ''}>Next</button>
        </div>
    `;
}
```

### Step 5 — Add helper functions

```javascript
function changeVendorPage(delta) {
    vendorPage += delta;
    filterTable();  // filterTable calls renderGrid
}

function changeVendorPageSize(size) {
    vendorPageSize = parseInt(size);
    localStorage.setItem('bmm_vendors_pageSize', vendorPageSize);
    vendorPage = 1;
    filterTable();
}
```

### Step 6 — Add pagination-bar CSS

Add the same pagination-bar styles that the items page uses:
```css
.pagination-bar { display:flex; align-items:center; justify-content:space-between; margin-top:1rem; font-size:0.78rem; color:var(--text-light); }
.pagination-bar button {
    padding:0.3rem 0.8rem; background:var(--surface-2); border:1px solid var(--border);
    color:var(--text-light); font-size:0.72rem; cursor:pointer; font-family:'Roboto',sans-serif;
    transition:background 0.15s, color 0.15s;
}
.pagination-bar button:hover:not(:disabled) { background:var(--gold-dim); color:var(--gold); }
.pagination-bar button:disabled { opacity:0.3; cursor:default; }
```

### Step 7 — Reset page on search

In `filterTable()`, add `vendorPage = 1;` at the top so searching always starts from page 1.

### Step 8 — Set dropdown value on load

After vendors load, set: `document.getElementById('vendor-page-size').value = vendorPageSize;`

---

## Design notes
- Dropdown styling should match the existing BMM-POS dark editorial style (dark surface, light text, gold hover)
- The page size preference is saved to localStorage so it persists between sessions
- Default to 25 per page for both pages
- Pagination bar shows "Showing 1–25 of 120 items/vendors" with Prev/Next buttons

## Test
1. Vendor items page: change to 10 per page → only 10 items show, Prev/Next work
2. Vendor items page: works in both grid view and list view
3. Admin vendors page: change to 10 per page → only 10 vendors show, Prev/Next work
4. Page size preference persists after page reload (stored in localStorage)
5. Searching resets to page 1
6. Commit and push to main
