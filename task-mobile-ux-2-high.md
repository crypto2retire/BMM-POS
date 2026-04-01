# Task: Mobile UX — High Priority Fixes (Dashboard + Login)

Fixes for dashboard rent layout, assistant input overflow, login tap targets, and choice screen readability.

---

## Fix 1: Dashboard rent section — stack vertically on mobile

File: `frontend/vendor/dashboard.html`

The rent card (line ~83) uses a flex row with `min-width:180px` on the status div, which breaks on 375px phones. Make it stack vertically on mobile.

Find (line ~88):

```html
<div style="flex:1;min-width:180px;">
```

Replace with:

```html
<div style="flex:1;min-width:0;">
```

Then find the parent flex container (line ~83):

```html
<div style="display:flex;align-items:center;gap:1.5rem;flex-wrap:wrap;">
```

Replace with:

```html
<div class="rent-card-layout" style="display:flex;align-items:center;gap:1.5rem;flex-wrap:wrap;">
```

And add this CSS inside the dashboard's `<style>` block (inside an existing or new mobile media query):

```css
@media (max-width: 767px) {
    .rent-card-layout {
        flex-direction: column !important;
        align-items: stretch !important;
        gap: 1rem !important;
    }
    .rent-card-layout .btn { width: 100%; }
}
```

---

## Fix 2: Dashboard assistant name input — remove min-width

File: `frontend/vendor/dashboard.html`

Find (line ~114):

```html
<input type="text" id="assistant-name-input" placeholder="e.g. Rosie, Max, Sage" maxlength="50"
    style="flex:1;min-width:180px;max-width:280px;padding:0.5rem 0.75rem;font-size:0.85rem;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:'Roboto',sans-serif;">
```

Replace with:

```html
<input type="text" id="assistant-name-input" placeholder="e.g. Rosie, Max, Sage" maxlength="50"
    style="flex:1;min-width:0;max-width:280px;padding:0.5rem 0.75rem;font-size:0.85rem;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:'Roboto',sans-serif;">
```

---

## Fix 3: Login "Forgot password" link — bigger tap target

File: `frontend/vendor/login.html`

The inline link (line ~188) is only 0.8rem with no padding. Add padding for a larger touch target.

Find:

```html
<a href="/vendor/forgot-password.html" style="font-size: 0.8rem; color: #5a554d; text-decoration: none; font-family: 'Roboto', sans-serif; transition: color 0.2s;" onmouseover="this.style.color='#C9A84C'" onmouseout="this.style.color='#5a554d'">Forgot your password?</a>
```

Replace with:

```html
<a href="/vendor/forgot-password.html" style="font-size: 0.85rem; color: #5a554d; text-decoration: none; font-family: 'Roboto', sans-serif; transition: color 0.2s; display:inline-block; padding:0.5rem 1rem;" onmouseover="this.style.color='#C9A84C'" onmouseout="this.style.color='#5a554d'">Forgot your password?</a>
```

Also update the CSS class (line ~62-63):

Find:

```css
.login-footer a {
    font-size: 0.68rem;
```

Replace with:

```css
.login-footer a {
    font-size: 0.78rem;
```

---

## Fix 4: Login choice screen description text — larger font

File: `frontend/vendor/login.html`

Find (line ~152):

```css
.choice-desc {
    font-family: 'Roboto', sans-serif;
    font-size: 0.75rem;
```

Replace with:

```css
.choice-desc {
    font-family: 'Roboto', sans-serif;
    font-size: 0.85rem;
```

---

## Summary

1. Rent section stacks vertically on mobile instead of overflowing
2. Assistant name input no longer forces 180px min-width
3. "Forgot password" link is larger with padding for easier tapping
4. Choice screen description text bumped from 0.75rem to 0.85rem

No backend changes. Commit and push when done.
