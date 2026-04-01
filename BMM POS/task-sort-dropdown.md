# Task: Add Sort Dropdown to Vendor Items Page

## File to edit
`frontend/vendor/items.html`

## What to do

Add a "Sort by" dropdown in the toolbar (between the search input and the view toggle buttons) that lets the user switch between Newest First and Oldest First. This should work in both grid view and list view.

## Current state
- `sortColumn` is already initialized to `'created_at'` and `sortDirection` to `'desc'` (line ~612-613) — this is correct, newest first is the default
- The toolbar is at line ~316 inside `<div class="items-toolbar" id="items-toolbar">`
- The `renderItems()` function already calls `getSortedItems()` which respects `sortColumn` and `sortDirection`
- List view table headers already have clickable sort arrows, but grid view has no sort control

## Step 1 — Add the dropdown HTML

Inside the `.items-toolbar` div (after the search input, before the view-toggle div), add:

```html
<select id="sort-order" onchange="setSortOrder(this.value)"
    style="padding:0.4rem 0.6rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text-light); font-size:0.72rem; font-family:'Roboto',sans-serif; cursor:pointer">
    <option value="desc" selected>Newest First</option>
    <option value="asc">Oldest First</option>
</select>
```

## Step 2 — Add the JavaScript function

Add this function near the existing `setSort()` function (around line ~1517):

```javascript
function setSortOrder(dir) {
    sortColumn = 'created_at';
    sortDirection = dir;
    renderItems();
}
```

## Step 3 — Keep dropdown in sync

In the existing `setSort(col)` function, add a line at the end to update the dropdown value if the sort column is `created_at`:

```javascript
// At end of setSort(col):
const dd = document.getElementById('sort-order');
if (dd) dd.value = (sortColumn === 'created_at') ? sortDirection : 'desc';
```

## Design notes
- Match the existing view-toggle button styling (same font-size, padding, border, colors)
- The dropdown should use the same dark surface background as other toolbar controls
- On mobile the toolbar already wraps (`flex-wrap: wrap`) so the dropdown will flow naturally

## Test
1. Open vendor/items.html, verify "Newest First" is selected by default
2. Switch to "Oldest First" — items should reorder with oldest at top
3. Switch back to "Newest First" — items should reorder with newest at top
4. Works in both grid view and list view
5. Commit and push to main
