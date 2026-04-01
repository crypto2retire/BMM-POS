# Task: Admin Pages UX Improvements (Mobile/Tablet)

Touch target and responsive fixes across admin pages. Focus on the most impactful issues.

---

## File 1: `frontend/admin/vendors.html`

### Fix 1: Pagination buttons — add min-height for touch

Find (around line 57-63):

```css
.pagination-bar button {
    padding:0.3rem 0.8rem; background:var(--surface-2); border:1px solid var(--border);
    color:var(--text-light); font-size:0.72rem; cursor:pointer; font-family:'Roboto',sans-serif;
    transition:background 0.15s, color 0.15s;
}
```

Replace with:

```css
.pagination-bar button {
    padding:0.45rem 0.8rem; background:var(--surface-2); border:1px solid var(--border);
    color:var(--text-light); font-size:0.78rem; cursor:pointer; font-family:'Roboto',sans-serif;
    transition:background 0.15s, color 0.15s; min-height:44px;
}
```

### Fix 2: Role badges — slightly larger

Find (around line 67-76):

```css
.role-badge {
    display: inline-block;
    padding: 2px 8px;
    font-size: 0.6rem;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    border: 1px solid transparent;
    font-family: 'Roboto', sans-serif;
}
```

Replace with:

```css
.role-badge {
    display: inline-block;
    padding: 4px 10px;
    font-size: 0.68rem;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    border: 1px solid transparent;
    font-family: 'Roboto', sans-serif;
}
```

### Fix 3: Search input — full width on mobile

Find (around line 94-96):

```css
.search-bar input {
    flex: 1;
    max-width: 340px;
```

Replace with:

```css
.search-bar input {
    flex: 1;
    max-width: 420px;
```

And add to the existing mobile media query (or create one if it doesn't exist — look for `@media (max-width: 767px)` in the page's `<style>` block):

```css
@media (max-width: 767px) {
    .search-bar input { max-width: 100%; min-height: 44px; font-size: 16px; }
    .search-bar { flex-wrap: wrap; }
}
```

If the page already has a `@media (max-width: 767px)` block, add these rules inside it. Don't duplicate the media query.

---

## File 2: `frontend/admin/rent.html`

### Fix 4: Flag button and record-pay button — bigger touch targets

Find (around line 75-86):

```css
.flag-btn {
    background: none;
    border: 1px solid var(--border);
    color: var(--text-light);
    cursor: pointer;
    padding: 3px 8px;
    font-size: 0.75rem;
    transition: border-color 0.2s, color 0.2s;
    font-family: 'Roboto', sans-serif;
}
.flag-btn:hover { border-color: var(--text-light); color: var(--text); }
.flag-btn.flagged { border-color: #c87070; color: #c87070; }
```

Replace with:

```css
.flag-btn {
    background: none;
    border: 1px solid var(--border);
    color: var(--text-light);
    cursor: pointer;
    padding: 8px 12px;
    font-size: 0.78rem;
    min-height: 40px;
    transition: border-color 0.2s, color 0.2s;
    font-family: 'Roboto', sans-serif;
}
.flag-btn:hover { border-color: var(--text-light); color: var(--text); }
.flag-btn.flagged { border-color: #c87070; color: #c87070; }
```

Find (around line 121-132):

```css
.record-pay-btn {
    background: rgba(123,196,160,0.12);
    color: #7BC4A0;
    border: 1px solid rgba(123,196,160,0.3);
    padding: 4px 12px;
    font-size: 0.72rem;
    cursor: pointer;
    font-family: 'Roboto', sans-serif;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    transition: background 0.15s, border-color 0.15s;
}
```

Replace with:

```css
.record-pay-btn {
    background: rgba(123,196,160,0.12);
    color: #7BC4A0;
    border: 1px solid rgba(123,196,160,0.3);
    padding: 8px 14px;
    font-size: 0.78rem;
    min-height: 40px;
    cursor: pointer;
    font-family: 'Roboto', sans-serif;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    transition: background 0.15s, border-color 0.15s;
}
```

### Fix 5: Rent search input — full width on mobile

Find the rent page's search bar input style (around line 94-100):

```css
.search-bar input {
    flex: 1;
    max-width: 340px;
```

Replace with:

```css
.search-bar input {
    flex: 1;
    max-width: 420px;
```

Add a mobile media query if one doesn't exist in rent.html's `<style>` block:

```css
@media (max-width: 767px) {
    .search-bar input { max-width: 100%; min-height: 44px; font-size: 16px; }
    .search-bar { flex-wrap: wrap; }
}
```

---

## File 3: `frontend/admin/settings.html`

### Fix 6: Role grid — bigger checkboxes + readable headers on mobile

Find (around line 233-236):

```css
.role-grid-row > div input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: var(--gold);
    cursor: pointer;
}
```

Replace with:

```css
.role-grid-row > div input[type="checkbox"] {
    width: 20px;
    height: 20px;
    accent-color: var(--gold);
    cursor: pointer;
}
```

Find (around line 205-206):

```css
.role-grid-header {
    font-size: 0.6rem;
```

Replace with:

```css
.role-grid-header {
    font-size: 0.7rem;
```

Find the mobile media query (around line 244):

```css
.role-grid-header { font-size: 0.55rem; }
```

Replace with:

```css
.role-grid-header { font-size: 0.62rem; }
```

---

## File 4: `frontend/static/css/main.css`

### Fix 7: Add table scroll support (global fix for all admin pages)

The `.table-wrapper` class already has `overflow-x: auto` (line 573). Good. But add touch scrolling support.

Find (around line 573):

```css
.table-wrapper { overflow-x: auto; }
```

Replace with:

```css
.table-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; }
```

Also add word-break to table cells so long text doesn't overflow:

Find (around line 574 — right after the `.table-wrapper` rule):

```css
table { width: 100%; border-collapse: collapse; }
```

Replace with:

```css
table { width: 100%; border-collapse: collapse; }
td { word-break: break-word; overflow-wrap: break-word; }
```

---

## Summary

1. **Vendors:** Pagination buttons get 44px height, role badges slightly larger, search input full-width on mobile
2. **Rent:** Flag and record-pay buttons enlarged for touch, search input responsive
3. **Settings:** Role grid checkboxes 16→20px, headers more readable
4. **Global CSS:** Table wrapper gets touch scroll support, td gets word-break

No backend changes. Commit and push when done.
