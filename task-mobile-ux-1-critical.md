# Task: Mobile UX — Critical Fixes (Batch Actions Dropdown + Filter Bar)

Vendors use phones and iPads. These fixes address the worst mobile layout issues on `frontend/vendor/items.html`.

---

## Fix 1: Convert batch actions bar to "More Actions" dropdown on mobile

The batch actions bar (line ~277) has 6 buttons that wrap into a messy jumble on phones. Replace the inline buttons with a primary action + "More Actions" dropdown.

### Step A — Add CSS (inside the `<style>` block, before the closing `</style>`)

Add:

```css
/* ── Batch actions mobile ────────────────────────── */
.batch-actions-inline { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
.batch-more-wrap { position: relative; }
.batch-more-btn {
    font-size: 0.75rem; padding: 0.4rem 1rem; background: var(--surface-2);
    border: 1px solid var(--border); color: var(--text-light); cursor: pointer;
    font-family: 'Roboto', sans-serif;
}
.batch-more-btn:hover { background: var(--gold-dim); color: var(--gold); border-color: var(--gold-dim); }
.batch-more-menu {
    display: none; position: absolute; top: 100%; left: 0; z-index: 50;
    background: var(--surface); border: 1px solid var(--warm-border);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4); min-width: 200px; margin-top: 4px;
}
.batch-more-menu.open { display: block; }
.batch-more-menu button {
    display: block; width: 100%; text-align: left; padding: 0.7rem 1rem;
    background: none; border: none; border-bottom: 1px solid rgba(201,169,110,0.1);
    color: var(--text-light); font-size: 0.82rem; cursor: pointer;
    font-family: 'Roboto', sans-serif;
}
.batch-more-menu button:last-child { border-bottom: none; }
.batch-more-menu button:hover { background: rgba(201,169,110,0.08); color: var(--gold); }

@media (min-width: 768px) {
    .batch-mobile-only { display: none !important; }
}
@media (max-width: 767px) {
    .batch-desktop-only { display: none !important; }
    .batch-actions-inline { gap: 0.5rem; }
}
```

### Step B — Replace the batch actions bar HTML (line ~277-285)

Find:

```html
<div id="batch-actions-bar" style="display:none; align-items:center; gap:0.75rem; margin-bottom:1rem; padding:0.75rem 1rem; background:var(--surface); border:1px solid var(--warm-border); flex-wrap:wrap">
    <span style="font-size:0.8rem; color:var(--text)"><strong id="selected-count">0</strong> selected</span>
    <button class="btn btn-primary" id="batch-print-btn" onclick="printSelectedLabels()" style="font-size:0.75rem; padding:0.4rem 1rem">Print Selected Labels</button>
    <button class="btn btn-outline" onclick="selectUnprinted()" style="font-size:0.72rem; padding:0.35rem 0.8rem">Select Unprinted</button>
    <button class="btn btn-outline" onclick="toggleSelectAll()" style="font-size:0.72rem; padding:0.35rem 0.8rem">Select All</button>
    <button class="btn btn-primary" onclick="openBulkSaleModal()" style="font-size:0.75rem; padding:0.4rem 1rem; background:#C9A96E; border-color:#C9A96E; color:#38383B">Apply Sale</button>
    <button class="btn btn-outline" onclick="bulkClearSale()" style="font-size:0.72rem; padding:0.35rem 0.8rem; color:#F59E0B; border-color:rgba(245,158,11,0.3)">Clear Sale</button>
    <button class="btn btn-secondary" onclick="clearSelection()" style="font-size:0.72rem; padding:0.35rem 0.8rem">Clear</button>
</div>
```

Replace with:

```html
<div id="batch-actions-bar" style="display:none; align-items:center; gap:0.75rem; margin-bottom:1rem; padding:0.75rem 1rem; background:var(--surface); border:1px solid var(--warm-border); flex-wrap:wrap">
    <span style="font-size:0.8rem; color:var(--text)"><strong id="selected-count">0</strong> selected</span>

    <!-- Desktop: all buttons visible -->
    <button class="btn btn-primary batch-desktop-only" id="batch-print-btn" onclick="printSelectedLabels()" style="font-size:0.75rem; padding:0.4rem 1rem">Print Selected Labels</button>
    <button class="btn btn-outline batch-desktop-only" onclick="selectUnprinted()" style="font-size:0.72rem; padding:0.35rem 0.8rem">Select Unprinted</button>
    <button class="btn btn-outline batch-desktop-only" onclick="toggleSelectAll()" style="font-size:0.72rem; padding:0.35rem 0.8rem">Select All</button>
    <button class="btn btn-primary batch-desktop-only" onclick="openBulkSaleModal()" style="font-size:0.75rem; padding:0.4rem 1rem; background:#C9A96E; border-color:#C9A96E; color:#38383B">Apply Sale</button>
    <button class="btn btn-outline batch-desktop-only" onclick="bulkClearSale()" style="font-size:0.72rem; padding:0.35rem 0.8rem; color:#F59E0B; border-color:rgba(245,158,11,0.3)">Clear Sale</button>
    <button class="btn btn-secondary batch-desktop-only" onclick="clearSelection()" style="font-size:0.72rem; padding:0.35rem 0.8rem">Clear</button>

    <!-- Mobile: primary actions + More dropdown -->
    <button class="btn btn-primary batch-mobile-only" onclick="printSelectedLabels()" style="font-size:0.78rem; padding:0.5rem 1rem">Print Labels</button>
    <button class="btn btn-outline batch-mobile-only" onclick="toggleSelectAll()" style="font-size:0.78rem; padding:0.5rem 0.8rem">Select All</button>
    <div class="batch-more-wrap batch-mobile-only">
        <button class="batch-more-btn" onclick="toggleBatchMenu(event)">More Actions ▾</button>
        <div class="batch-more-menu" id="batch-more-menu">
            <button onclick="openBulkSaleModal(); closeBatchMenu()">Apply Sale</button>
            <button onclick="bulkClearSale(); closeBatchMenu()">Clear Sale</button>
            <button onclick="selectUnprinted(); closeBatchMenu()">Select Unprinted</button>
            <button onclick="clearSelection(); closeBatchMenu()">Clear Selection</button>
        </div>
    </div>
</div>
```

### Step C — Add JavaScript functions (in the `<script>` block, near the other batch functions)

Add these functions:

```javascript
function toggleBatchMenu(e) {
    e.stopPropagation();
    document.getElementById('batch-more-menu').classList.toggle('open');
}
function closeBatchMenu() {
    document.getElementById('batch-more-menu').classList.remove('open');
}
// Close menu when tapping elsewhere
document.addEventListener('click', function() { closeBatchMenu(); });
```

---

## Fix 2: Remove hardcoded min-width on filter selects

The label type select (line ~305) has `min-width:120px` and label size select (line ~312) has `min-width:180px`. These force overflow on small phones. The mobile CSS already overrides with `width: 100% !important; min-width: 0 !important;` BUT inline styles beat CSS selectors. Remove the inline min-widths.

### Step A — Label Type select (line ~305)

Find:

```html
<select id="label-pref-select" class="form-control" onchange="saveLabelPref()" style="width:auto;min-width:120px;font-size:0.78rem;padding:0.3rem 0.5rem;height:auto">
```

Replace with:

```html
<select id="label-pref-select" class="form-control" onchange="saveLabelPref()" style="width:auto;font-size:0.78rem;padding:0.3rem 0.5rem;height:auto">
```

### Step B — Label Size select (line ~312)

Find:

```html
<select id="label-size-select" class="form-control" onchange="saveLabelSize()" style="width:auto;min-width:180px;font-size:0.78rem;padding:0.3rem 0.5rem;height:auto">
```

Replace with:

```html
<select id="label-size-select" class="form-control" onchange="saveLabelSize()" style="width:auto;font-size:0.78rem;padding:0.3rem 0.5rem;height:auto">
```

---

## Fix 3: Make items toolbar stack properly on mobile

The toolbar (line ~318-337) has search, page size, sort, and view toggle all in one row. Add CSS to stack it on phones.

In the existing `@media (max-width: 767px)` block inside the `<style>` tag (around line 118-126), find:

```css
@media (max-width: 767px) {
    .desktop-only { display:none !important; }
    .items-toolbar { gap: 0.5rem; }
    .items-toolbar .search-input { min-width: 0; width: 100%; order: -1; }
    .filter-label-bar { flex-direction: column; align-items: stretch !important; gap: 0.6rem !important; }
    .filter-label-bar .status-filter-bar { justify-content: flex-start; }
    .filter-label-bar > div[style*="display:flex"] { width: 100%; }
    .filter-label-bar select { width: 100% !important; min-width: 0 !important; }
}
```

Replace with:

```css
@media (max-width: 767px) {
    .desktop-only { display:none !important; }
    .items-toolbar {
        gap: 0.5rem;
        flex-wrap: wrap;
    }
    .items-toolbar .search-input { min-width: 0; width: 100%; order: -1; }
    .items-toolbar select {
        flex: 1; min-width: 0; font-size: 0.78rem !important;
        padding: 0.5rem 0.6rem !important; min-height: 44px;
    }
    .items-toolbar .view-toggle { margin-left: auto; }
    .filter-label-bar { flex-direction: column; align-items: stretch !important; gap: 0.6rem !important; }
    .filter-label-bar .status-filter-bar { justify-content: flex-start; }
    .filter-label-bar > div[style*="display:flex"] { width: 100%; }
    .filter-label-bar select { width: 100% !important; min-width: 0 !important; }
}
```

---

## Summary

1. Batch actions bar → desktop shows all 6 buttons, mobile shows Print Labels + Select All + "More Actions" dropdown
2. Filter selects → removed hardcoded `min-width` that overrode mobile CSS
3. Items toolbar → selects flex to fill space, 44px touch height on mobile

No backend changes. Commit and push when done.
