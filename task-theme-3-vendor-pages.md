# Task: Light/Dark Mode — Part 3: Vendor Page Color Refactoring

Convert hardcoded colors in vendor pages to CSS variables so they respond to the light/dark theme system. **Do NOT change the login page** — it has its own parchment aesthetic that works in both modes.

**Prerequisite:** Parts 1 and 2 must be deployed (backend preferences + CSS theme system + theme-loader.js).

---

## Strategy

The light theme works by overriding CSS variables via `[data-theme="light"]` on the `<html>` element. For this to work, all colors must reference CSS variables instead of hardcoded hex/rgba values.

**Color mapping reference** (use these for replacements):

| Hardcoded color | Replace with | Purpose |
|----------------|-------------|---------|
| `#38383B`, `#2A2825`, `#1e1e20` | `var(--bg)` | Background |
| `#44444A`, `#353230` | `var(--surface)` | Cards, panels |
| `#4e4e54`, `#3E3B38` | `var(--surface-2)` | Inputs, secondary surfaces |
| `#555558`, `#4A4643` | `var(--border)` | Borders |
| `rgba(201,169,110,0.22)`, `rgba(201,168,76,0.25)` | `var(--warm-border)` | Gold accent borders |
| `#F0EDE8`, `#F5F0E8` | `var(--text)` | Primary text |
| `#A8A6A1`, `#B5AFA5` | `var(--text-light)` | Secondary text |
| `#8A847A` | `var(--text-muted)` | Muted text |
| `#C9A96E`, `#C9A84C` | `var(--gold)` | Gold accents |
| `#9E8339` | `var(--gold-dim)` | Darker gold |
| `#D4B96A` | `var(--gold-light)` | Lighter gold |
| `rgba(201,169,110,0.12)`, `rgba(201,168,76,0.12)` | `var(--gold-glow)` | Gold glow effects |
| `#ffffff`, `#fff` | `var(--white)` | Pure white (use sparingly) |
| `#1a1a1d`, `#1a1a1a` | Keep as-is | Used for text ON gold buttons (intentional contrast) |
| `#f87171`, `#C06060` | `var(--danger)` or keep hardcoded | Error/danger red |
| `#4ade80`, `#7BC4A0`, `#065F46` | `var(--success)` or keep hardcoded | Success green |
| `#fbbf24`, `#F59E0B`, `#92400E` | `var(--warning)` or keep hardcoded | Warning amber |
| `#6495ed` | `var(--info)` or keep hardcoded | Info blue |

**Rules:**
1. Replace background/surface/text/border colors → CSS variables (these are what change between themes)
2. Status/semantic colors (red, green, amber, blue) → can stay hardcoded if they work in both themes. If they use background-with-text patterns, check contrast in light mode.
3. `rgba()` values for subtle overlays → replace with variable-based equivalents where possible
4. Colors inside JavaScript `style.color = '#xxx'` assignments → replace with CSS classes or variable references
5. Colors in `onmouseover`/`onmouseout` handlers → replace with CSS `:hover` rules using variables

---

## Files to update

### 1. `frontend/vendor/dashboard.html`

This file has ~23 hardcoded color instances. Focus on:

**In the `<style>` block:**
- Replace any hardcoded background colors with `var(--surface)` or `var(--bg)`
- Replace text colors with `var(--text)` or `var(--text-light)`
- Replace border colors with `var(--border)` or `var(--warm-border)`

**In inline styles:**
- `style="color: #C9A96E"` → `style="color: var(--gold)"`
- `style="color: #A8A6A1"` → `style="color: var(--text-light)"`
- `style="background: #1e1e20"` → `style="background: var(--bg)"`
- Any `#F0EDE8` or similar → `var(--text)`

**In JavaScript:**
- Look for `style.color = '#...'` or `style.background = '#...'` and replace with CSS variable references
- Look for dynamically generated HTML with hardcoded colors (e.g., badge backgrounds) and replace with CSS classes
- Status badge colors (paid=green, unpaid=red, partial=amber) can use:
  - `background: rgba(var(--success), 0.12)` pattern OR keep the existing rgba values since they're semantic and work in both themes

### 2. `frontend/vendor/items.html`

This file has ~46 hardcoded color instances. Focus on:

**In the `<style>` block:**
- All background/surface/border/text colors → CSS variables
- Status badge colors and filter button colors

**In inline styles:**
- Same mapping as above
- Pay attention to the batch actions bar, filter selects, and pagination

**In JavaScript:**
- Item status badges generated dynamically
- Toast/alert messages
- Modal backgrounds

---

## Important notes

- **Do NOT touch `frontend/vendor/login.html`** — it uses a unique parchment color scheme that works independently of the theme system
- **Test by setting** `data-theme="light"` on the `<html>` element in browser dev tools after making changes
- **Preserve the visual design** — the goal is NOT to change how the dark theme looks. It should look exactly the same. Only the light theme should look different.
- **When in doubt, use CSS variables** — if a color is ambiguous, using a variable is safer than leaving it hardcoded
- Some `rgba()` values can't directly use CSS variables. For these, add new CSS variables if needed, or use the `[data-theme="light"]` selector to override them specifically.

Commit and push when done.
