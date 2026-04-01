# Task: Fix Navbar Visibility in Light Mode

## Problem
When light mode is active, the navbar background becomes `#FFFFFF` but the text colors remain hardcoded for dark backgrounds — making the logo, menu links, and user name invisible (white-on-white).

## Root Cause
These navbar styles use hardcoded light colors that don't adapt to light mode:
- `.navbar-brand` → `color: var(--white)` (white on white background)
- `.navbar-nav a` → `color: rgba(245,240,232,0.45)` (hardcoded light cream)
- `.navbar-nav a:hover` → `color: var(--parchment)` (this one flips correctly)
- `.navbar-user > span` → inherits white from `.navbar`
- `.navbar` → `color: var(--white)` (sets default text color to white)
- Mobile `.navbar-nav` → `background: var(--charcoal-deep)` (hardcoded in `@media`)
- Mobile `.navbar-nav a` → `border-bottom: 1px solid rgba(245,240,232,0.03)` (hardcoded)

## File to Edit
`frontend/static/css/main.css`

## Exact Changes

Find this existing block (around line 126-134):

```css
/* Light theme navbar */
[data-theme="light"] .navbar {
    background: #FFFFFF;
    border-bottom-color: var(--border);
}
[data-theme="light"] .mobile-nav-dropdown {
    background: #FFFFFF;
    border-color: var(--border);
}
```

**Replace it entirely** with this expanded block:

```css
/* Light theme navbar */
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
[data-theme="light"] .navbar-nav a:hover {
    color: var(--text);
    background: rgba(26,24,21,0.05);
}
[data-theme="light"] .navbar-nav a.active {
    color: var(--gold);
    background: rgba(153,111,26,0.08);
    border-bottom-color: var(--gold);
}
[data-theme="light"] .navbar-user > span {
    color: var(--text-muted);
}
[data-theme="light"] .nav-hamburger,
[data-theme="light"] .hamburger-btn {
    color: var(--text);
}
[data-theme="light"] .mobile-nav-dropdown {
    background: #FFFFFF;
    border-color: var(--border);
    box-shadow: 0 8px 24px rgba(0,0,0,0.10);
}
[data-theme="light"] .mobile-nav-dropdown a {
    color: var(--text);
    border-bottom-color: var(--border);
}
[data-theme="light"] .mobile-nav-dropdown a:hover {
    background: rgba(153,111,26,0.06);
    color: var(--gold);
}
```

Then find the mobile media query section (around line 1153-1173) and add these overrides **right after** the closing `}` of the existing `.navbar-nav a` mobile rule (after line 1173):

**Add this new block** (do NOT replace existing mobile rules — add after them):

```css
    /* Light mode mobile nav overrides */
    [data-theme="light"] .navbar-nav {
        background: #FFFFFF;
        border-top-color: var(--border);
    }
    [data-theme="light"] .navbar-nav a {
        color: rgba(26,24,21,0.65);
        border-bottom: 1px solid var(--border);
    }
    [data-theme="light"] .navbar-nav a:hover {
        background: rgba(153,111,26,0.06);
        color: var(--gold);
    }
```

## Logo Visibility Note
The navbar logo (`img.navbar-logo`) may be designed for dark backgrounds. If it's hard to see on white after this fix, we can add a CSS filter:
```css
[data-theme="light"] .navbar-logo {
    filter: brightness(0.2);
}
```
**Only add this if the logo is hard to see after testing.** Don't add it preemptively — it depends on the image.

## Testing
1. Log in as any role (vendor, admin, cashier)
2. Switch to Light mode via Display Settings
3. Verify the navbar shows:
   - Logo visible
   - Menu links visible (dark text on white background)
   - Active page link highlighted in gold
   - Hover effect works (text darkens, subtle background)
   - User name/role text visible
4. On mobile (or narrow browser), verify:
   - Hamburger icon visible
   - Mobile dropdown menu has white background with dark text
5. Switch back to Dark mode — verify navbar still looks correct (no regressions)
6. Check admin pages, vendor pages, and POS page — all should have visible navbars in both modes

## No Other Files Changed
This is CSS-only — no backend or JavaScript changes needed.
