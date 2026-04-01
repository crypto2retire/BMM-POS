# Task: Mobile UX — Medium Fixes (Pagination, Touch Targets, Table Scroll)

Polish fixes for the vendor items page. All changes in `frontend/vendor/items.html`.

---

## Fix 1: Pagination — responsive layout on mobile

The pagination bar tries to fit 5 buttons + text in one row, which gets cramped on phones. Add mobile-specific CSS.

Find the pagination CSS block (around line 226-234):

```css
/* Pagination */
.pagination-bar { display:flex; align-items:center; justify-content:space-between; margin-top:1rem; font-size:0.78rem; color:var(--text-light); }
.pagination-bar button {
    padding:0.35rem 0.8rem; background:var(--surface-2); border:1px solid var(--border);
    color:var(--text-light); cursor:pointer; font-size:0.72rem; font-family:'Roboto',sans-serif;
    transition:background 0.15s;
}
.pagination-bar button:hover:not(:disabled) { background:var(--gold-dim); color:var(--gold); }
.pagination-bar button:disabled { opacity:0.3; cursor:default; }
```

Replace with:

```css
/* Pagination */
.pagination-bar { display:flex; align-items:center; justify-content:space-between; margin-top:1rem; font-size:0.78rem; color:var(--text-light); }
.pagination-bar button {
    padding:0.35rem 0.8rem; background:var(--surface-2); border:1px solid var(--border);
    color:var(--text-light); cursor:pointer; font-size:0.72rem; font-family:'Roboto',sans-serif;
    transition:background 0.15s; min-height:44px;
}
.pagination-bar button:hover:not(:disabled) { background:var(--gold-dim); color:var(--gold); }
.pagination-bar button:disabled { opacity:0.3; cursor:default; }
@media (max-width: 480px) {
    .pagination-bar {
        flex-direction: column; gap: 0.5rem; align-items: stretch;
    }
    .pagination-bar > span { text-align: center; }
    .pagination-bar > div { justify-content: center; }
}
```

This stacks the "Showing X–Y" text above the buttons on very small phones, and ensures 44px touch height on all pagination buttons.

---

## Fix 2: Label dropdown toggle button — larger touch target

Find (around line 35):

```css
.label-btn-toggle { padding:0.3rem 0.5rem !important; min-width:36px; }
```

Replace with:

```css
.label-btn-toggle { padding:0.3rem 0.5rem !important; min-width:44px; min-height:44px; }
```

---

## Fix 3: Mini chat photo button — larger touch target

Find (around line 537-538):

```html
<button type="button" id="mini-chat-photo-btn" title="Send a photo"
    style="background:#4e4e54;border:none;color:#fff;font-size:0.85rem;cursor:pointer;min-height:36px;min-width:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0">
```

Replace with:

```html
<button type="button" id="mini-chat-photo-btn" title="Send a photo"
    style="background:#4e4e54;border:none;color:#fff;font-size:1rem;cursor:pointer;min-height:44px;min-width:44px;display:flex;align-items:center;justify-content:center;flex-shrink:0;border-radius:0">
```

---

## Fix 4: List view table — add horizontal scroll wrapper

The list view table has 8 columns that overflow on phones. Wrap it in a scrollable container.

In the JavaScript that builds the list view table, find the code that creates the opening `<table>` tag. It will be something like:

```javascript
html += `<table class="items-list-table">`;
```

Wrap the entire table in a scroll container by changing the opening to:

```javascript
html += `<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -0.5rem;padding:0 0.5rem">`;
html += `<table class="items-list-table" style="min-width:700px">`;
```

And after the closing `</table>` tag, add the closing `</div>`:

Find where it ends the table:

```javascript
html += `</table>`;
```

Change to:

```javascript
html += `</table></div>`;
```

This lets the table scroll horizontally on phones while keeping it full-width on desktop.

---

## Fix 5: List view action buttons — bigger for touch

Find (around line 224):

```css
.items-list-table .actions-cell button { padding:0.25rem 0.5rem; font-size:0.68rem; }
```

Replace with:

```css
.items-list-table .actions-cell button { padding:0.35rem 0.6rem; font-size:0.72rem; min-height:36px; }
```

---

## Summary

1. Pagination stacks vertically on small phones (≤480px), buttons get 44px touch height
2. Label dropdown toggle bumped to 44px touch target
3. Mini chat photo button bumped to 44px touch target
4. List view table wrapped in horizontal scroll container for mobile
5. List view action buttons slightly larger for easier tapping

No backend changes. Commit and push when done.
