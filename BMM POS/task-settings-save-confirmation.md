# Task: Add Clear Save Confirmation on Admin Settings Page

## Problem
When clicking "Save Settings" on the admin settings page, the confirmation message ("Settings saved successfully") is a tiny text span next to the button that's easy to miss and disappears after 4 seconds. Users don't realize their settings saved.

## Solution
Add a prominent banner-style confirmation that slides in at the top of the settings panel, with a checkmark icon and auto-dismiss after 5 seconds. Also add visual feedback on the Save button itself (brief text change).

## File: `frontend/admin/settings.html`

### Change 1: Add toast/banner CSS

Find the `#save-status` CSS rule (around line 194):

```css
        #save-status {
            font-size: 0.82rem;
            margin-left: auto;
        }
```

**Replace with:**

```css
        #save-status {
            font-size: 0.82rem;
            margin-left: auto;
        }

        .save-banner {
            position: fixed;
            top: 70px;
            left: 50%;
            transform: translateX(-50%);
            z-index: 9999;
            padding: 0.85rem 2rem;
            font-size: 0.95rem;
            font-weight: 600;
            font-family: 'Roboto', sans-serif;
            letter-spacing: 0.03em;
            border: 1px solid;
            box-shadow: 0 4px 20px rgba(0,0,0,0.25);
            animation: bannerSlide 0.3s ease;
            white-space: nowrap;
        }
        .save-banner.success {
            background: var(--success);
            color: #fff;
            border-color: var(--success-light);
        }
        .save-banner.error {
            background: var(--danger);
            color: #fff;
            border-color: var(--danger-dark);
        }
        @keyframes bannerSlide {
            from { opacity: 0; transform: translateX(-50%) translateY(-20px); }
            to { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
```

### Change 2: Update the `saveSettings()` function

Find (around line 1079):

```javascript
    async function saveSettings() {
        var data = {};
        getAllSettingIds().forEach(function(key) {
            var el = document.getElementById('s-' + key);
            if (!el) return;
            if (el.type === 'checkbox') {
                data[key] = el.checked ? 'true' : 'false';
            } else {
                data[key] = el.value;
            }
        });

        var statusEl = document.getElementById('save-status');
        try {
            await apiPost('/api/v1/admin/settings', data);
            statusEl.innerHTML = '<span style="color:var(--success-light)">Settings saved successfully</span>';
            setTimeout(function() { statusEl.innerHTML = ''; }, 4000);
        } catch (e) {
            statusEl.innerHTML = '<span style="color:var(--danger)">' + (e.message || 'Failed to save') + '</span>';
        }
    }
```

**Replace with:**

```javascript
    function showSaveBanner(message, type) {
        var existing = document.querySelector('.save-banner');
        if (existing) existing.remove();
        var banner = document.createElement('div');
        banner.className = 'save-banner ' + (type || 'success');
        banner.textContent = (type === 'error' ? '✕ ' : '✓ ') + message;
        document.body.appendChild(banner);
        setTimeout(function() {
            banner.style.opacity = '0';
            banner.style.transition = 'opacity 0.3s';
            setTimeout(function() { banner.remove(); }, 300);
        }, 5000);
    }

    async function saveSettings() {
        var data = {};
        getAllSettingIds().forEach(function(key) {
            var el = document.getElementById('s-' + key);
            if (!el) return;
            if (el.type === 'checkbox') {
                data[key] = el.checked ? 'true' : 'false';
            } else {
                data[key] = el.value;
            }
        });

        var btn = document.querySelector('.save-bar .btn-save');
        var originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Saving...';

        try {
            await apiPost('/api/v1/admin/settings', data);
            btn.textContent = '✓ Saved!';
            showSaveBanner('Settings saved successfully', 'success');
            setTimeout(function() {
                btn.textContent = originalText;
                btn.disabled = false;
            }, 2000);
        } catch (e) {
            btn.textContent = originalText;
            btn.disabled = false;
            showSaveBanner(e.message || 'Failed to save settings', 'error');
        }
    }
```

### Change 3: Also update `saveEmailTemplate()` with the same pattern

Find (around line 1177):

```javascript
    async function saveEmailTemplate() {
```

Read ahead to find the full function and update its success/error handling to also use `showSaveBanner`:

In its try block, after the apiPost succeeds, replace any `statusEl.innerHTML = ...` success line with:
```javascript
            showSaveBanner('Email template saved successfully', 'success');
```

And in its catch block, replace any `statusEl.innerHTML = ...` error line with:
```javascript
            showSaveBanner(e.message || 'Failed to save template', 'error');
```

## What This Does
1. **Save button changes text** to "Saving..." while the API call runs, then "✓ Saved!" for 2 seconds — immediate visual feedback
2. **Prominent banner** slides in from the top center of the page — green for success, red for error — impossible to miss
3. Banner auto-dismisses after 5 seconds with a fade
4. Works in both light and dark mode (uses `var(--success)` and `var(--danger)` which adapt)

## Testing
1. Go to Admin Settings
2. Change any setting value
3. Click "Save Settings"
4. Verify: button says "Saving..." then "✓ Saved!", and a green banner appears at top
5. Wait 5 seconds — banner fades out
6. Test with a bad scenario if possible (e.g., disconnect network) — should show red error banner
7. Test in both light and dark mode

## One file changed
- `frontend/admin/settings.html`
