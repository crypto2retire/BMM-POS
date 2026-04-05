# Task: Hide Archived Vendors by Default — Add Status Filter

Archived vendors should be hidden from the main vendor list. Add a status filter dropdown that defaults to showing only active vendors. Archived vendors are shown only when explicitly selected.

---

## File: `frontend/admin/vendors.html`

### Change 1: Add status filter dropdown to the search bar

Find the search bar (around line 290-300):

```html
<div class="search-bar">
    <input type="text" id="search-input" placeholder="Filter by name or booth number&hellip;" oninput="filterTable()">
    <select id="vendor-page-size" onchange="changeVendorPageSize(this.value)"
        style="padding:0.4rem 0.6rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text-light); font-size:0.72rem; font-family:'Roboto',sans-serif; cursor:pointer">
        <option value="10">10 per page</option>
        <option value="25">25 per page</option>
        <option value="50">50 per page</option>
        <option value="100">100 per page</option>
    </select>
    <button class="btn btn-primary" id="add-vendor-btn" onclick="openAddModal()">+ Add Vendor</button>
</div>
```

Replace with:

```html
<div class="search-bar" style="flex-wrap:wrap">
    <input type="text" id="search-input" placeholder="Filter by name or booth number&hellip;" oninput="filterTable()">
    <select id="vendor-status-filter" onchange="filterTable()"
        style="padding:0.4rem 0.6rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text-light); font-size:0.78rem; font-family:'Roboto',sans-serif; cursor:pointer; min-height:44px">
        <option value="active" selected>Active Vendors</option>
        <option value="all-active">Active + Suspended</option>
        <option value="archived">Archived Only</option>
        <option value="all">All Vendors</option>
    </select>
    <select id="vendor-page-size" onchange="changeVendorPageSize(this.value)"
        style="padding:0.4rem 0.6rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text-light); font-size:0.72rem; font-family:'Roboto',sans-serif; cursor:pointer">
        <option value="10">10 per page</option>
        <option value="25">25 per page</option>
        <option value="50">50 per page</option>
        <option value="100">100 per page</option>
    </select>
    <button class="btn btn-primary" id="add-vendor-btn" onclick="openAddModal()">+ Add Vendor</button>
</div>
```

### Change 2: Update filterTable() to respect status filter

Find the `filterTable` function (around line 617-626):

```javascript
function filterTable() {
    vendorPage = 1;
    const q = document.getElementById('search-input').value.trim().toLowerCase();
    const filtered = q
        ? allVendors.filter(v =>
            v.name.toLowerCase().includes(q) ||
            (v.booth_number && v.booth_number.toLowerCase().includes(q)))
        : allVendors;
    renderGrid(filtered);
}
```

Replace with:

```javascript
function getFilteredVendors() {
    const q = document.getElementById('search-input').value.trim().toLowerCase();
    const statusFilter = document.getElementById('vendor-status-filter').value;

    let filtered = allVendors;

    // Status filter
    if (statusFilter === 'active') {
        filtered = filtered.filter(v => v.status === 'active');
    } else if (statusFilter === 'all-active') {
        filtered = filtered.filter(v => v.status !== 'archived');
    } else if (statusFilter === 'archived') {
        filtered = filtered.filter(v => v.status === 'archived');
    }
    // 'all' shows everything

    // Text search
    if (q) {
        filtered = filtered.filter(v =>
            v.name.toLowerCase().includes(q) ||
            (v.booth_number && v.booth_number.toLowerCase().includes(q)));
    }

    return filtered;
}

function filterTable() {
    vendorPage = 1;
    renderGrid(getFilteredVendors());
}
```

### Change 3: Update changeVendorPage() to use the same filter logic

Find (around line 723-733):

```javascript
function changeVendorPage(delta) {
    vendorPage += delta;
    // Re-run filter without resetting page
    const q = document.getElementById('search-input').value.trim().toLowerCase();
    const filtered = q
        ? allVendors.filter(v =>
            v.name.toLowerCase().includes(q) ||
            (v.booth_number && v.booth_number.toLowerCase().includes(q)))
        : allVendors;
    renderGrid(filtered);
}
```

Replace with:

```javascript
function changeVendorPage(delta) {
    vendorPage += delta;
    renderGrid(getFilteredVendors());
}
```

### Change 4: Update goToVendorPage() the same way

Find (around line 735-744):

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

Replace with:

```javascript
function goToVendorPage(page) {
    vendorPage = page;
    renderGrid(getFilteredVendors());
}
```

### Change 5: Update the initial render call to filter too

Find the init function where it first renders (around line 1097):

```javascript
renderGrid(allVendors);
```

Replace with:

```javascript
renderGrid(getFilteredVendors());
```

**Important:** Do NOT change the `renderGrid(allVendors)` calls inside the action functions (archiveVendor, unarchiveVendor, suspendVendor, activateVendor, createVendor). Those should also use the filter. Find every `renderGrid(allVendors)` call and replace with `renderGrid(getFilteredVendors())`.

There should be approximately 5-6 of these calls throughout the file (in archiveVendor, unarchiveVendor, suspendVendor, activateVendor, createVendor, and init). Replace ALL of them with `renderGrid(getFilteredVendors())`.

---

## Summary

- Default view shows only **Active** vendors
- Dropdown options: Active Vendors | Active + Suspended | Archived Only | All Vendors
- Status filter combines with text search
- All pagination and action functions respect the filter
- Archived vendors are completely hidden unless user explicitly selects "Archived Only" or "All Vendors"

No backend changes needed — filtering is client-side since all vendors are already loaded. Commit and push when done.
