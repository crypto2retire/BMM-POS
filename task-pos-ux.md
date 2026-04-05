# Task: POS Terminal UX Improvements (Mobile/Tablet)

Cashiers need to move fast. These fixes address undersized touch targets, unresponsive layouts, and cramped elements across both POS pages.

---

## File 1: `frontend/pos/index.html`

### Fix 1: Qty +/- buttons too small (24px → 44px)

Find (around line 217-231):

```css
.qty-control { display: flex; align-items: center; gap: 0.25rem; }
.qty-control button {
    width: 24px;
    height: 24px;
    border: 1px solid #555558;
    background: #4e4e54;
    color: #F0EDE8;
    cursor: pointer;
    font-size: 0.85rem;
    line-height: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.12s;
}
.qty-control button:hover { background: #5a5a62; }
```

Replace with:

```css
.qty-control { display: flex; align-items: center; gap: 0.35rem; }
.qty-control button {
    width: 44px;
    height: 44px;
    border: 1px solid #555558;
    background: #4e4e54;
    color: #F0EDE8;
    cursor: pointer;
    font-size: 1.1rem;
    line-height: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.12s;
}
.qty-control button:hover { background: #5a5a62; }
```

### Fix 2: Cart table headers too small (0.62rem → 0.75rem)

Find (around line 187):

```css
.cart-table th {
    text-align: left;
    font-size: 0.62rem;
```

Replace with:

```css
.cart-table th {
    text-align: left;
    font-size: 0.75rem;
```

### Fix 3: Quick cash buttons too short

Find (around line 417):

```css
.quick-cash button {
    flex: 1;
    min-width: 50px;
    background: var(--surface-2);
    border: 1px solid rgba(255,255,255,0.1);
    color: #F0EDE8;
    padding: 0.55rem 0.4rem;
    cursor: pointer;
    font-size: 0.82rem;
```

Replace with:

```css
.quick-cash button {
    flex: 1;
    min-width: 50px;
    min-height: 44px;
    background: var(--surface-2);
    border: 1px solid rgba(255,255,255,0.1);
    color: #F0EDE8;
    padding: 0.65rem 0.5rem;
    cursor: pointer;
    font-size: 0.88rem;
```

### Fix 4: Denomination inputs too small (4px padding)

Find (around line 798-821):

```css
.denom-row {
    display: flex;
    align-items: center;
    gap: 4px;
    background: #2D2D30;
    padding: 4px 8px;
}
.denom-row label {
    font-size: 0.72rem;
    color: #A8A6A1;
    min-width: 55px;
    font-family: 'Roboto', sans-serif;
}
.denom-row input {
    width: 50px;
    background: #44444A;
    border: 1px solid #555558;
    color: #F0EDE8;
    padding: 4px 6px;
    font-size: 0.85rem;
    text-align: center;
    font-family: 'Roboto Mono', monospace;
}
```

Replace with:

```css
.denom-row {
    display: flex;
    align-items: center;
    gap: 8px;
    background: #2D2D30;
    padding: 8px 12px;
}
.denom-row label {
    font-size: 0.8rem;
    color: #A8A6A1;
    min-width: 55px;
    font-family: 'Roboto', sans-serif;
}
.denom-row input {
    width: 60px;
    background: #44444A;
    border: 1px solid #555558;
    color: #F0EDE8;
    padding: 8px 6px;
    font-size: 0.9rem;
    text-align: center;
    font-family: 'Roboto Mono', monospace;
    min-height: 40px;
}
```

### Fix 5: Manual form inputs too short (~31px)

Find (around line 775-784):

```css
.manual-form-group input, .manual-form-group select {
    width: 100%;
    background: #2a2a2d;
    border: 1px solid #555558;
    color: #F0EDE8;
    padding: 0.55rem 0.7rem;
    font-size: 0.875rem;
    font-family: 'Roboto', sans-serif;
    box-sizing: border-box;
}
```

Replace with:

```css
.manual-form-group input, .manual-form-group select {
    width: 100%;
    background: #2a2a2d;
    border: 1px solid #555558;
    color: #F0EDE8;
    padding: 0.7rem 0.75rem;
    font-size: 1rem;
    font-family: 'Roboto', sans-serif;
    box-sizing: border-box;
    min-height: 44px;
}
```

### Fix 6: Navbar links too small on tablets — add wrapping

Find (around line 101-112):

```css
.pos-navbar-right a, .pos-navbar-right button.nav-link {
    color: rgba(240,237,232,0.6);
    text-decoration: none;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.72rem;
    padding: 0.3rem 0.6rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-family: 'Roboto', sans-serif;
    transition: color 0.15s, background 0.15s;
}
```

Replace with:

```css
.pos-navbar-right a, .pos-navbar-right button.nav-link {
    color: rgba(240,237,232,0.6);
    text-decoration: none;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.78rem;
    padding: 0.5rem 0.7rem;
    min-height: 44px;
    display: inline-flex;
    align-items: center;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-family: 'Roboto', sans-serif;
    transition: color 0.15s, background 0.15s;
}
```

### Fix 7: Modal max-width needs mobile fallback

Find (around line 374-382):

```css
.pos-modal {
    background: #44444A;
    border: 1px solid rgba(201,169,110,0.25);
    padding: 1.75rem;
    width: 100%;
    max-width: 460px;
    color: #F0EDE8;
    box-shadow: 0 20px 50px rgba(0,0,0,0.6), 0 0 0 1px rgba(201,169,110,0.08);
    animation: fadeUp 0.25s ease;
}
```

Replace with:

```css
.pos-modal {
    background: #44444A;
    border: 1px solid rgba(201,169,110,0.25);
    padding: 1.75rem;
    width: calc(100% - 2rem);
    max-width: 460px;
    max-height: 90vh;
    overflow-y: auto;
    color: #F0EDE8;
    box-shadow: 0 20px 50px rgba(0,0,0,0.6), 0 0 0 1px rgba(201,169,110,0.08);
    animation: fadeUp 0.25s ease;
}
```

### Fix 8: Receipt modal same issue

Find (around line 590):

```css
.receipt-modal { max-width: 380px; max-height: 85vh; overflow-y: auto; }
```

Replace with:

```css
.receipt-modal { width: calc(100% - 2rem); max-width: 380px; max-height: 85vh; overflow-y: auto; }
```

### Fix 9: Mobile pay buttons — remove max-width so they fill space

Find (around line 1207):

```html
<button class="pay-btn cash" id="mobile-cash-btn" onclick="openCashModal()" disabled style="flex:1;max-width:140px;padding:0.75rem">
```

Replace with:

```html
<button class="pay-btn cash" id="mobile-cash-btn" onclick="openCashModal()" disabled style="flex:1;padding:0.75rem;min-height:48px;font-size:0.9rem">
```

Find (around line 1210):

```html
<button class="pay-btn card" id="mobile-card-btn" onclick="startCardPayment()" disabled style="flex:1;max-width:140px;padding:0.75rem">
```

Replace with:

```html
<button class="pay-btn card" id="mobile-card-btn" onclick="startCardPayment()" disabled style="flex:1;padding:0.75rem;min-height:48px;font-size:0.9rem">
```

---

## File 2: `frontend/pos/register.html`

### Fix 10: Add mobile responsive layout (register has NO media queries!)

Add this inside the `<style>` block, just before the closing `</style>`:

```css
/* ── Mobile responsive ───────────────────────────── */
@media (max-width: 767px) {
    .reg-layout {
        flex-direction: column;
        height: auto;
        min-height: calc(100vh - 56px);
        overflow: auto;
    }
    .reg-left {
        flex: none;
        max-height: 50vh;
        overflow-y: auto;
    }
    .reg-right {
        flex: none;
        overflow: visible;
    }
    .results-area {
        grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    }
    .pay-btn { min-height: 44px; font-size: 0.9rem; padding: 0.65rem; }
    .cash-input-row input { min-height: 44px; font-size: 1rem; padding: 0.6rem; }
    .btn-charge { min-height: 52px; font-size: 0.95rem; }
    .receipt-card { width: calc(100% - 2rem); max-width: 420px; }
}

@media (max-width: 1023px) and (min-width: 768px) {
    .reg-layout { /* keep side-by-side on tablet */ }
    .reg-left { flex: 0 0 55%; }
    .reg-right { flex: 0 0 45%; }
}
```

### Fix 11: Qty buttons too small (22px → 40px)

Find (around line 224-235):

```css
.qty-btn {
    width: 22px; height: 22px;
    border: 1px solid #555558;
    border-radius: 0;
    background: #44444A;
    color: #F0EDE8;
    cursor: pointer;
    font-size: 0.85rem;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.1s;
}
```

Replace with:

```css
.qty-btn {
    width: 40px; height: 40px;
    border: 1px solid #555558;
    border-radius: 0;
    background: #44444A;
    color: #F0EDE8;
    cursor: pointer;
    font-size: 1rem;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.1s;
}
```

### Fix 12: Receipt card hardcoded width — add fallback

Find (around line 390-394):

```css
.receipt-card {
    background: #44444A;
    border: 1px solid rgba(201,169,110,0.25);
    border-radius: 0;
    width: 420px;
```

Replace with:

```css
.receipt-card {
    background: #44444A;
    border: 1px solid rgba(201,169,110,0.25);
    border-radius: 0;
    width: 100%;
    max-width: 420px;
```

---

## Summary

**index.html (POS terminal):**
1. Qty buttons: 24px → 44px
2. Cart headers: 0.62rem → 0.75rem
3. Quick cash buttons: added min-height 44px
4. Denomination inputs: padding 4px → 8px, min-height 40px
5. Manual form inputs: padding bumped, min-height 44px
6. Navbar links: padding bumped, min-height 44px
7. Modal: added mobile width fallback + max-height
8. Receipt modal: added mobile width fallback
9. Mobile pay buttons: removed max-width cap, bigger touch targets

**register.html:**
10. Added full mobile media query (was completely missing!)
11. Qty buttons: 22px → 40px
12. Receipt card: fixed to responsive width

No backend changes. Commit and push when done.
