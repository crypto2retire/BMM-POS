# Task: Light/Dark Mode + Font Size — Part 2: CSS Theme System + Theme Loader

Create the light theme CSS variables, the font size system, and a shared JavaScript theme loader that every page will include.

**Prerequisite:** Part 1 (backend) must be deployed.

---

## Step 1: Add light theme variables to main.css

File: `frontend/static/css/main.css`

Add this block immediately AFTER the existing `:root { ... }` block (after the closing `}` around line 68):

```css
/* ── LIGHT THEME ─────────────────────────────────────────── */
/* Warm parchment light theme — high-contrast, easy on the eyes */
[data-theme="light"] {
    /* ── Core Palette (light) ─────────────────────── */
    --charcoal:      #F7F4EE;
    --charcoal-deep: #EDE8DC;
    --charcoal-mid:  #F0ECE4;
    --parchment:     #2A2825;
    --cream:         #353230;
    --cream-dark:    #4A4643;

    /* ── Semantic Colors (light) ──────────────────── */
    --bg:            #F7F4EE;
    --surface:       #FFFFFF;
    --surface-2:     #F0ECE4;
    --border:        #D4CFC5;
    --warm-border:   rgba(160,130,50,0.30);
    --text:          #1A1815;
    --text-light:    #5A5650;
    --text-muted:    #8A847A;
    --white:         #ffffff;

    --gold:          #996F1A;
    --gold-dim:      #7A5914;
    --gold-light:    #B8862E;
    --gold-glow:     rgba(153,111,26,0.10);

    --primary:       var(--gold);
    --primary-dark:  var(--gold-dim);
    --primary-light: var(--gold-light);

    --danger:        #9B3728;
    --danger-dark:   #7E2D21;
    --success:       #3D7A2E;
    --success-light: #4F9140;
    --warning:       #9E7A1E;
    --info:          #2E6A80;

    --secondary:     var(--text-light);
    --secondary-dark: #8A847A;

    /* ── Shadows (light) ──────────────────────────── */
    --shadow:        0 2px 8px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md:     0 6px 20px rgba(0,0,0,0.10), 0 2px 6px rgba(0,0,0,0.06);
    --shadow-warm:   0 4px 24px rgba(0,0,0,0.08), 0 0 0 1px var(--warm-border);
    --shadow-lg:     0 16px 48px rgba(0,0,0,0.12), 0 4px 12px rgba(0,0,0,0.06);
    --shadow-parchment: 0 4px 20px rgba(0,0,0,0.06), 0 1px 4px rgba(0,0,0,0.03);
}

/* Light theme body background override */
[data-theme="light"] body,
[data-theme="light"] {
    background-image: none;
    background-color: var(--bg);
}

/* Light theme navbar */
[data-theme="light"] .navbar {
    background: #FFFFFF;
    border-bottom-color: var(--border);
}
[data-theme="light"] .mobile-nav-dropdown {
    background: #FFFFFF;
    border-color: var(--border);
}

/* Light theme inputs */
[data-theme="light"] input,
[data-theme="light"] select,
[data-theme="light"] textarea {
    background: #FFFFFF;
    border-color: var(--border);
    color: var(--text);
}

/* Light theme table rows */
[data-theme="light"] .ledger-table tr:nth-child(even) td,
[data-theme="light"] .verify-table tr:nth-child(even) td {
    background: rgba(0,0,0,0.02);
}

/* Light theme buttons */
[data-theme="light"] .btn-primary {
    background: var(--gold);
    color: #FFFFFF;
}
[data-theme="light"] .btn-primary:hover {
    background: var(--gold-dim);
}

/* Light theme alerts */
[data-theme="light"] .alert-success {
    background: rgba(61,122,46,0.08);
    border-color: rgba(61,122,46,0.25);
    color: #2D6420;
}
[data-theme="light"] .alert-error {
    background: rgba(155,55,40,0.08);
    border-color: rgba(155,55,40,0.25);
    color: #7E2D21;
}

/* Light theme scrollbar */
[data-theme="light"] ::-webkit-scrollbar-track { background: var(--surface-2); }
[data-theme="light"] ::-webkit-scrollbar-thumb { background: var(--border); }
[data-theme="light"] ::selection { background: rgba(153,111,26,0.20); color: var(--text); }
```

---

## Step 2: Add font size system to main.css

Add this block after the light theme block:

```css
/* ── FONT SIZE SYSTEM ────────────────────────────────────── */
[data-font-size="small"]  { font-size: 14px !important; }
[data-font-size="medium"] { font-size: 16px !important; }
[data-font-size="large"]  { font-size: 18px !important; }

/* Scale headings proportionally */
[data-font-size="small"] h1 { font-size: 1.6rem; }
[data-font-size="small"] h2 { font-size: 1.3rem; }
[data-font-size="small"] h3 { font-size: 1.1rem; }
[data-font-size="medium"] h1 { font-size: 1.75rem; }
[data-font-size="medium"] h2 { font-size: 1.4rem; }
[data-font-size="medium"] h3 { font-size: 1.15rem; }
[data-font-size="large"] h1 { font-size: 2rem; }
[data-font-size="large"] h2 { font-size: 1.6rem; }
[data-font-size="large"] h3 { font-size: 1.3rem; }

/* Ensure table text scales */
[data-font-size="large"] td,
[data-font-size="large"] th { font-size: 0.92rem; }
[data-font-size="small"] td,
[data-font-size="small"] th { font-size: 0.78rem; }
```

---

## Step 3: Create the shared theme loader JavaScript

Create a new file: `frontend/static/js/theme-loader.js`

This script runs on every page. It loads the user's preferences from the API and applies them immediately. It also provides a fast localStorage cache so the theme doesn't flash on page load.

```javascript
/**
 * BMM-POS Theme Loader
 * Include this script on every page, BEFORE the closing </body> tag.
 * It reads the user's theme + font size preferences and applies them.
 */
(function() {
    'use strict';

    // ── 1. Apply cached preferences IMMEDIATELY to prevent flash ──
    var cachedTheme = localStorage.getItem('bmm_theme') || 'dark';
    var cachedFontSize = localStorage.getItem('bmm_font_size') || 'medium';
    document.documentElement.setAttribute('data-theme', cachedTheme);
    document.documentElement.setAttribute('data-font-size', cachedFontSize);

    // ── 2. Once DOM is ready, fetch real preferences from API ──
    var token = sessionStorage.getItem('bmm_token');
    if (token) {
        fetch('/api/v1/auth/me', {
            headers: { 'Authorization': 'Bearer ' + token }
        })
        .then(function(res) {
            if (!res.ok) return null;
            return res.json();
        })
        .then(function(data) {
            if (!data) return;
            var theme = data.theme_preference || 'dark';
            var fontSize = data.font_size_preference || 'medium';

            // Update DOM
            document.documentElement.setAttribute('data-theme', theme);
            document.documentElement.setAttribute('data-font-size', fontSize);

            // Update cache for next page load (prevents flash)
            localStorage.setItem('bmm_theme', theme);
            localStorage.setItem('bmm_font_size', fontSize);
        })
        .catch(function() {
            // Silently fail — cached values are already applied
        });
    }

    // ── 3. Global helper functions for settings pages ──
    window.bmmSetTheme = function(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('bmm_theme', theme);
        return fetch('/api/v1/auth/me/preferences', {
            method: 'PUT',
            headers: {
                'Authorization': 'Bearer ' + sessionStorage.getItem('bmm_token'),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ theme_preference: theme }),
        });
    };

    window.bmmSetFontSize = function(size) {
        document.documentElement.setAttribute('data-font-size', size);
        localStorage.setItem('bmm_font_size', size);
        return fetch('/api/v1/auth/me/preferences', {
            method: 'PUT',
            headers: {
                'Authorization': 'Bearer ' + sessionStorage.getItem('bmm_token'),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ font_size_preference: size }),
        });
    };
})();
```

---

## Step 4: Include theme-loader.js on EVERY page

Add this script tag to every HTML file, BEFORE any other `<script>` tags (ideally right after the opening `<body>` tag, or at the very start of the script section):

```html
<script src="/static/js/theme-loader.js"></script>
```

Files to update (add the script tag):

**Vendor pages:**
- `frontend/vendor/login.html`
- `frontend/vendor/dashboard.html`
- `frontend/vendor/items.html`

**POS pages:**
- `frontend/pos/index.html`
- `frontend/pos/register.html`

**Admin pages:**
- `frontend/admin/index.html`
- `frontend/admin/vendors.html`
- `frontend/admin/rent.html`
- `frontend/admin/reports.html`
- `frontend/admin/settings.html`
- `frontend/admin/studio.html`
- `frontend/admin/eod-reports.html`
- `frontend/admin/payouts.html`
- `frontend/admin/customers.html`
- `frontend/admin/inventory-verify.html`

**Public pages:**
- `frontend/shop/index.html`

**IMPORTANT:** The script tag must be placed INSIDE the `<body>`, as early as possible. The best location is right after `<body>` opens:

```html
<body>
<script src="/static/js/theme-loader.js"></script>
<!-- rest of page content -->
```

This ensures the theme is applied before any content renders.

---

## Summary

This task creates the foundation:
1. **Light theme CSS variables** that override all the dark theme colors when `data-theme="light"` is set on `<html>`
2. **Font size system** using `data-font-size` attribute on `<html>`
3. **Shared theme-loader.js** that loads preferences, caches them, and provides `bmmSetTheme()` / `bmmSetFontSize()` helpers
4. **Script included on all 16 pages**

After this is deployed, pages that already use CSS variables (like reports.html, eod-reports.html, admin/index.html) will automatically support light mode. Pages with hardcoded colors will need per-page refactoring in subsequent tasks.

Commit and push when done.
