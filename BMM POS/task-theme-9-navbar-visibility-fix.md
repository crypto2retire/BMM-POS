# Task: Fix Navbar Logo & Link Visibility in Light Mode (Round 2)

## Problem
Light mode is working but the navbar logo and menu links are still hard to see. Three issues:

1. **Logo is invisible** — the logo image (`logo.webp`) is designed for dark backgrounds (light/white colored). On the white/parchment navbar, it disappears.
2. **Nav links too faint** — `rgba(26,24,21,0.55)` isn't strong enough contrast.
3. **Dashboard inline style** — `dashboard.html` has `style="background:var(--bg)"` on the navbar, which overrides the CSS. Need `!important` on the CSS rule to guarantee white navbar.

## File 1: `frontend/static/css/main.css`

Find this block (around line 127):

```css
[data-theme="light"] .navbar {
    background: #FFFFFF;
    color: var(--text);
    border-bottom: 2px solid var(--gold);
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
[data-theme="light"] .navbar-brand {
    color: var(--text);
}
[data-theme="light"] .navbar-brand .store-name {
    opacity: 0.55;
}
[data-theme="light"] .navbar-nav a {
    color: rgba(26,24,21,0.55);
}
```

**Replace with:**

```css
[data-theme="light"] .navbar {
    background: #FFFFFF !important;
    color: var(--text);
    border-bottom: 2px solid var(--gold);
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
[data-theme="light"] .navbar-logo {
    filter: brightness(0.15) contrast(1.2);
}
[data-theme="light"] .navbar-brand {
    color: var(--text);
}
[data-theme="light"] .navbar-brand .store-name {
    color: var(--text-light);
    opacity: 0.75;
}
[data-theme="light"] .navbar-nav a {
    color: var(--text-light);
}
```

### What changed:
- `background: #FFFFFF !important` — forces white background even when inline styles exist
- Added `.navbar-logo { filter: brightness(0.15) contrast(1.2); }` — darkens the light logo image so it's visible on white
- `.store-name` uses `color: var(--text-light)` with higher opacity (0.75 instead of 0.55)
- `.navbar-nav a` now uses `var(--text-light)` (`#5A5650`) instead of rgba at 55% — much more readable

## File 2: `frontend/vendor/dashboard.html`

Also remove the inline style that conflicts. Find (line 40):

```html
<nav class="navbar" style="background:var(--bg);">
```

**Replace with:**

```html
<nav class="navbar">
```

## File 3: `frontend/vendor/booth-showcase.html`

Find (line 188):

```html
<nav class="navbar" style="background:#1e1e20;">
```

**Replace with:**

```html
<nav class="navbar">
```

The CSS handles both dark and light backgrounds — no inline styles needed.

## Testing
1. Switch to Light mode on the vendor dashboard
2. Verify:
   - Logo is visible (dark version of the logo on white background)
   - All nav links are clearly readable (dark text)
   - Active link is gold with underline
   - Navbar has white background with subtle gold bottom border
3. Switch back to Dark mode — verify logo looks normal (filter only applies in light mode)
4. Check vendor items page, admin pages, POS — all navbars should be consistent
5. Check booth-showcase page in both modes

## No backend changes needed
