# Task: Light/Dark Mode — Part 6: Settings UI for All Roles

Add theme toggle and font size controls to each role's settings area. Every user (vendor, cashier, admin) should be able to set their own preferences.

**Prerequisite:** Parts 1-2 must be deployed. Can run in parallel with Parts 3-5.

---

## Overview

Each role has a different settings location:
- **Vendors** → `frontend/vendor/dashboard.html` (add a "Display Settings" section)
- **Cashiers** → currently no settings page, so add controls to the POS page or create a small preferences area
- **Admin** → `frontend/admin/settings.html` (add a "Display Settings" section)

The theme-loader.js (from Part 2) provides two global helper functions:
- `bmmSetTheme('dark')` or `bmmSetTheme('light')` — saves to API + updates DOM
- `bmmSetFontSize('small')` or `bmmSetFontSize('medium')` or `bmmSetFontSize('large')` — saves to API + updates DOM

---

## Step 1: Add Display Settings to Vendor Dashboard

File: `frontend/vendor/dashboard.html`

Add a "Display Settings" section. Find a good location — ideally after the existing vendor settings/preferences area, or at the bottom of the dashboard before the AI assistant panel.

Add this HTML block:

```html
<div class="dash-section" style="margin-bottom:1.5rem">
    <div class="dash-section-title" style="font-family:'EB Garamond',Georgia,serif; font-size:1.15rem; font-weight:500; color:var(--text); margin-bottom:1rem">Display Settings</div>
    <div style="display:flex; gap:1.5rem; flex-wrap:wrap; align-items:flex-start">
        <div>
            <label style="font-size:0.72rem; color:var(--text-light); text-transform:uppercase; letter-spacing:0.1em; display:block; margin-bottom:0.3rem; font-family:'Roboto',sans-serif">Theme</label>
            <div style="display:flex; gap:0">
                <button id="theme-dark-btn" onclick="setThemePref('dark')" style="padding:0.5rem 1rem; font-size:0.82rem; font-family:'Roboto',sans-serif; cursor:pointer; border:1px solid var(--border); min-height:44px; transition:all 0.15s; background:var(--surface-2); color:var(--text-light)">
                    &#9790; Dark
                </button>
                <button id="theme-light-btn" onclick="setThemePref('light')" style="padding:0.5rem 1rem; font-size:0.82rem; font-family:'Roboto',sans-serif; cursor:pointer; border:1px solid var(--border); border-left:none; min-height:44px; transition:all 0.15s; background:var(--surface-2); color:var(--text-light)">
                    &#9788; Light
                </button>
            </div>
        </div>
        <div>
            <label style="font-size:0.72rem; color:var(--text-light); text-transform:uppercase; letter-spacing:0.1em; display:block; margin-bottom:0.3rem; font-family:'Roboto',sans-serif">Font Size</label>
            <select id="font-size-select" onchange="setFontPref(this.value)" style="padding:0.5rem 0.75rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text); font-size:0.82rem; font-family:'Roboto',sans-serif; min-height:44px">
                <option value="small">Small</option>
                <option value="medium" selected>Medium</option>
                <option value="large">Large</option>
            </select>
        </div>
    </div>
</div>
```

Add this JavaScript (in the existing `<script>` block or a new one):

```javascript
// ── Display preferences ───────────────────────
function setThemePref(theme) {
    bmmSetTheme(theme).then(function() {
        updateThemeButtons(theme);
    });
}

function setFontPref(size) {
    bmmSetFontSize(size);
}

function updateThemeButtons(theme) {
    var darkBtn = document.getElementById('theme-dark-btn');
    var lightBtn = document.getElementById('theme-light-btn');
    if (theme === 'dark') {
        darkBtn.style.background = 'var(--gold)';
        darkBtn.style.color = '#1a1a1d';
        darkBtn.style.borderColor = 'var(--gold)';
        lightBtn.style.background = 'var(--surface-2)';
        lightBtn.style.color = 'var(--text-light)';
        lightBtn.style.borderColor = 'var(--border)';
    } else {
        lightBtn.style.background = 'var(--gold)';
        lightBtn.style.color = '#1a1a1d';
        lightBtn.style.borderColor = 'var(--gold)';
        darkBtn.style.background = 'var(--surface-2)';
        darkBtn.style.color = 'var(--text-light)';
        darkBtn.style.borderColor = 'var(--border)';
    }
}

// Load current preferences on page load
function loadDisplayPrefs() {
    var token = sessionStorage.getItem('bmm_token');
    if (!token) return;
    fetch('/api/v1/auth/me', { headers: { 'Authorization': 'Bearer ' + token } })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var theme = data.theme_preference || 'dark';
            var fontSize = data.font_size_preference || 'medium';
            updateThemeButtons(theme);
            document.getElementById('font-size-select').value = fontSize;
        })
        .catch(function() {});
}

// Call on page load (add to existing init or DOMContentLoaded)
loadDisplayPrefs();
```

---

## Step 2: Add Display Settings to Admin Settings Page

File: `frontend/admin/settings.html`

Add a "Display Settings" section at the TOP of the settings page (before store settings), since it's a personal preference, not a store-wide setting. Use the same HTML and JavaScript as Step 1, with the same button IDs and functions.

The admin settings page likely already has sections for different settings categories. Add the Display Settings as a new section card at the top:

```html
<div style="background:var(--surface); border:1px solid var(--border); padding:1.25rem; margin-bottom:1.25rem">
    <h3 style="font-family:'EB Garamond',Georgia,serif; font-size:1.15rem; font-weight:500; color:var(--text); margin-bottom:1rem">
        Display Settings
        <span style="font-size:0.72rem; color:var(--text-light); font-family:'Roboto',sans-serif; font-weight:400; margin-left:0.5rem">(personal)</span>
    </h3>
    <!-- Same theme buttons + font size select as Step 1 -->
    <!-- Same JavaScript functions as Step 1 -->
</div>
```

---

## Step 3: Add Display Settings for Cashiers

Cashiers primarily use `frontend/pos/index.html`. Add a small preferences area accessible from the POS page.

The best approach: add a small gear icon button in the POS navbar area that opens a dropdown/modal with the theme and font size controls. Use the same HTML pattern as Steps 1-2 but in a compact dropdown format:

```html
<!-- Add near the navbar user area -->
<button onclick="toggleDisplayPrefs()" style="background:none; border:none; color:var(--text-light); font-size:1.1rem; cursor:pointer; padding:0.5rem; min-height:44px; min-width:44px" title="Display Settings">&#9881;</button>

<div id="display-prefs-dropdown" style="display:none; position:absolute; right:1rem; top:60px; background:var(--surface); border:1px solid var(--border); padding:1rem; z-index:100; min-width:220px; box-shadow:var(--shadow-md)">
    <div style="font-size:0.72rem; color:var(--text-light); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:0.5rem; font-family:'Roboto',sans-serif">Theme</div>
    <div style="display:flex; gap:0; margin-bottom:0.75rem">
        <button id="theme-dark-btn" onclick="setThemePref('dark')" style="flex:1; padding:0.4rem 0.5rem; font-size:0.78rem; font-family:'Roboto',sans-serif; cursor:pointer; border:1px solid var(--border); min-height:40px; background:var(--surface-2); color:var(--text-light)">&#9790; Dark</button>
        <button id="theme-light-btn" onclick="setThemePref('light')" style="flex:1; padding:0.4rem 0.5rem; font-size:0.78rem; font-family:'Roboto',sans-serif; cursor:pointer; border:1px solid var(--border); border-left:none; min-height:40px; background:var(--surface-2); color:var(--text-light)">&#9788; Light</button>
    </div>
    <div style="font-size:0.72rem; color:var(--text-light); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:0.3rem; font-family:'Roboto',sans-serif">Font Size</div>
    <select id="font-size-select" onchange="setFontPref(this.value)" style="width:100%; padding:0.4rem 0.5rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text); font-size:0.82rem; font-family:'Roboto',sans-serif; min-height:40px">
        <option value="small">Small</option>
        <option value="medium" selected>Medium</option>
        <option value="large">Large</option>
    </select>
</div>
```

Add the JavaScript toggle:
```javascript
function toggleDisplayPrefs() {
    var dd = document.getElementById('display-prefs-dropdown');
    dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
}
// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    var dd = document.getElementById('display-prefs-dropdown');
    if (dd && dd.style.display !== 'none' && !e.target.closest('#display-prefs-dropdown') && !e.target.closest('[onclick*="toggleDisplayPrefs"]')) {
        dd.style.display = 'none';
    }
});
```

Plus the same `setThemePref`, `setFontPref`, `updateThemeButtons`, and `loadDisplayPrefs` functions from Step 1.

---

## Summary

| Role | Location | UI Style |
|------|----------|----------|
| Vendor | `vendor/dashboard.html` | Section card with toggle + dropdown |
| Admin | `admin/settings.html` | Section card at top (marked "personal") |
| Cashier | `pos/index.html` | Gear icon → dropdown in navbar |

All three use the same `bmmSetTheme()` and `bmmSetFontSize()` global functions from `theme-loader.js`.

Commit and push when done.
