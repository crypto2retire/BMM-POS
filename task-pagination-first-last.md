# Task: Add First & Last Page Buttons to Pagination

Add "First" and "Last" buttons to the pagination controls on both the **vendor items page** and **admin vendors page**. Layout: `First | Prev | Page X of Y | Next | Last`.

---

## File 1: `frontend/vendor/items.html`

### Change A — Grid view pagination (around line 1863)

Find this block:

```javascript
grid.innerHTML += `<div class="pagination-bar" style="grid-column:1/-1">
    <span>Showing ${start + 1}&ndash;${end} of ${total} items</span>
    <div style="display:flex;gap:6px">
        <button onclick="changePage(-1)" ${currentPage <= 1 ? 'disabled' : ''}>Prev</button>
        <button onclick="changePage(1)" ${currentPage >= totalPages ? 'disabled' : ''}>Next</button>
    </div>
</div>`;
```

Replace with:

```javascript
grid.innerHTML += `<div class="pagination-bar" style="grid-column:1/-1">
    <span>Showing ${start + 1}&ndash;${end} of ${total} items</span>
    <div style="display:flex;gap:6px;align-items:center">
        <button onclick="goToPage(1)" ${currentPage <= 1 ? 'disabled' : ''}>First</button>
        <button onclick="changePage(-1)" ${currentPage <= 1 ? 'disabled' : ''}>Prev</button>
        <span style="font-size:0.72rem;color:var(--text-light)">Page ${currentPage} of ${totalPages}</span>
        <button onclick="changePage(1)" ${currentPage >= totalPages ? 'disabled' : ''}>Next</button>
        <button onclick="goToPage(${totalPages})" ${currentPage >= totalPages ? 'disabled' : ''}>Last</button>
    </div>
</div>`;
```

### Change B — List view pagination (around line 1947)

Find this block:

```javascript
html += `<div class="pagination-bar">
    <span>Showing ${start + 1}&ndash;${end} of ${total} items</span>
    <div style="display:flex;gap:6px">
        <button onclick="changePage(-1)" ${currentPage <= 1 ? 'disabled' : ''}>Prev</button>
        <button onclick="changePage(1)" ${currentPage >= totalPages ? 'disabled' : ''}>Next</button>
    </div>
</div>`;
```

Replace with:

```javascript
html += `<div class="pagination-bar">
    <span>Showing ${start + 1}&ndash;${end} of ${total} items</span>
    <div style="display:flex;gap:6px;align-items:center">
        <button onclick="goToPage(1)" ${currentPage <= 1 ? 'disabled' : ''}>First</button>
        <button onclick="changePage(-1)" ${currentPage <= 1 ? 'disabled' : ''}>Prev</button>
        <span style="font-size:0.72rem;color:var(--text-light)">Page ${currentPage} of ${totalPages}</span>
        <button onclick="changePage(1)" ${currentPage >= totalPages ? 'disabled' : ''}>Next</button>
        <button onclick="goToPage(${totalPages})" ${currentPage >= totalPages ? 'disabled' : ''}>Last</button>
    </div>
</div>`;
```

### Change C — Add goToPage function (around line 1961, next to `changePage`)

Find:

```javascript
function changePage(delta) {
    currentPage += delta;
    displayItems();
}
```

Replace with:

```javascript
function changePage(delta) {
    currentPage += delta;
    displayItems();
}

function goToPage(page) {
    currentPage = page;
    displayItems();
}
```

---

## File 2: `frontend/admin/vendors.html`

### Change D — Pagination HTML (around line 707)

Find:

```javascript
if (pagDiv) {
    pagDiv.innerHTML = `
        <span>Showing ${start + 1}&ndash;${end} of ${total} vendors</span>
        <div style="display:flex;gap:6px">
            <button onclick="changeVendorPage(-1)" ${vendorPage <= 1 ? 'disabled' : ''}>Prev</button>
            <button onclick="changeVendorPage(1)" ${vendorPage >= totalPages ? 'disabled' : ''}>Next</button>
        </div>
    `;
}
```

Replace with:

```javascript
if (pagDiv) {
    pagDiv.innerHTML = `
        <span>Showing ${start + 1}&ndash;${end} of ${total} vendors</span>
        <div style="display:flex;gap:6px;align-items:center">
            <button onclick="goToVendorPage(1)" ${vendorPage <= 1 ? 'disabled' : ''}>First</button>
            <button onclick="changeVendorPage(-1)" ${vendorPage <= 1 ? 'disabled' : ''}>Prev</button>
            <span style="font-size:0.72rem;color:var(--text-light)">Page ${vendorPage} of ${totalPages}</span>
            <button onclick="changeVendorPage(1)" ${vendorPage >= totalPages ? 'disabled' : ''}>Next</button>
            <button onclick="goToVendorPage(${totalPages})" ${vendorPage >= totalPages ? 'disabled' : ''}>Last</button>
        </div>
    `;
}
```

### Change E — Add goToVendorPage function (around line 728, next to `changeVendorPage`)

Find:

```javascript
function changeVendorPageSize(size) {
```

Add **above** it:

```javascript
function goToVendorPage(page) {
    vendorPage = page;
    const q = document.getElementById('search-input').value.trim().toLowerCase();
    const filtered = q
        ? allVendors.filter(v =>
            v.name.toLowerCase().includes(q) ||
            (v.booth_number && v.booth_number.toLowerCase().includes(q)))
        : allVendors;
    renderGrid(filtered);
}

```

---

## Summary

Both pages get:
- **First** button — jumps to page 1 (disabled when already on page 1)
- **Last** button — jumps to last page (disabled when already on last page)
- **Page X of Y** indicator between Prev and Next
- Layout: `First | Prev | Page X of Y | Next | Last`

No backend changes needed. Commit and push when done.
