# Task: Vendor Sale Notification Preference — Part 2 (Frontend)

## Overview
Add a "Sale Notifications" dropdown to the vendor dashboard Display Settings section, letting vendors choose: Instant, Daily Summary, Weekly Summary, or Monthly Summary.

**Depends on:** `task-vendor-sale-notify-pref-1-backend.md` must be deployed first.

---

## File: `frontend/vendor/dashboard.html`

### Change 1: Add the Notification Dropdown to Display Settings

Find the Display Settings section (around line 128-150). After the Font Size `</div>` (the one that closes the font-size wrapper, around line 148), add a new dropdown:

Find the closing `</div>` of the font-size block and the closing `</div>` of the flex container:
```html
            </div>
        </div>
```

Insert this **before** the closing `</div>` of the flex container (before line 149's `</div>`):

```html
            <div>
                <label style="font-size:0.72rem; color:var(--text-light); text-transform:uppercase; letter-spacing:0.1em; display:block; margin-bottom:0.3rem; font-family:'Roboto',sans-serif">Sale Notifications</label>
                <select id="sale-notify-select" onchange="setSaleNotifyPref(this.value)" style="padding:0.5rem 0.75rem; background:var(--surface-2); border:1px solid var(--border); color:var(--text); font-size:0.82rem; font-family:'Roboto',sans-serif; min-height:44px">
                    <option value="instant">Instant (every sale)</option>
                    <option value="daily">Daily Summary</option>
                    <option value="weekly">Weekly Summary</option>
                    <option value="monthly">Monthly Summary</option>
                </select>
            </div>
```

### Change 2: Add the JavaScript Function

Find where `window.setThemePref` and `window.setFontPref` are defined (in the script section). Add this new function nearby:

```javascript
    window.setSaleNotifyPref = function(val) {
        fetch('/api/v1/auth/me/preferences', {
            method: 'PUT',
            headers: {
                'Authorization': 'Bearer ' + sessionStorage.getItem('bmm_token'),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ sale_notify_preference: val }),
        })
        .then(function(res) {
            if (!res.ok) throw new Error('Failed to save');
            // Show brief confirmation
            var sel = document.getElementById('sale-notify-select');
            var origBorder = sel.style.borderColor;
            sel.style.borderColor = 'var(--success-light)';
            setTimeout(function() { sel.style.borderColor = origBorder; }, 1500);
        })
        .catch(function() {
            alert('Failed to save notification preference');
        });
    };
```

### Change 3: Load the Saved Preference

Find where the display preferences are loaded (the function that calls `/api/v1/auth/me` and sets the theme/font). It likely looks something like:

```javascript
window.loadDisplayPrefs = function() {
```

Or it may be inline in the init/load function. Wherever `theme_preference` and `font_size_preference` are read from the `/me` API response, add:

```javascript
            // Set sale notification dropdown
            var notifyPref = data.sale_notify_preference || 'instant';
            var notifySel = document.getElementById('sale-notify-select');
            if (notifySel) notifySel.value = notifyPref;
```

This should go right after the lines that set the theme buttons and font-size dropdown from the API response.

---

## Testing
1. Log in as a vendor
2. Go to the dashboard — Display Settings should now show three controls: Theme, Font Size, Sale Notifications
3. The dropdown should default to "Instant (every sale)" for existing vendors
4. Change to "Daily Summary" — the dropdown border should briefly flash green confirming the save
5. Refresh the page — the dropdown should still show "Daily Summary" (persisted)
6. Change back to "Instant (every sale)"
7. Test in both light and dark mode — dropdown should be readable in both

## One file changed
- `frontend/vendor/dashboard.html`
