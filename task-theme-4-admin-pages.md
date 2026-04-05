# Task: Light/Dark Mode — Part 4: Admin Page Color Refactoring

Convert hardcoded colors in admin pages to CSS variables so they respond to the light/dark theme system.

**Prerequisite:** Parts 1-2 must be deployed. Run this AFTER Part 3 (vendor pages).

---

## Strategy

Same color mapping as Part 3. Use the reference table from `task-theme-3-vendor-pages.md` for the color → variable mapping.

**Key rules:**
1. Background/surface/text/border colors → CSS variables
2. Status/semantic colors (red, green, amber) → keep hardcoded if they work in both themes
3. Colors in JS `.style.color` → use CSS classes or variable references
4. `onmouseover`/`onmouseout` handlers with colors → replace with CSS `:hover` rules
5. **Do NOT change** how the dark theme looks — it should be identical after refactoring

---

## Files to update (ordered by effort)

### Low effort (already use CSS variables heavily):

**1. `frontend/admin/reports.html`** (~3 hardcoded colors)
- Already mostly compliant. Fix any remaining hardcoded colors.

**2. `frontend/admin/eod-reports.html`** (~9 hardcoded colors)
- Status colors for report badges: `#7BC4A0`, `#6495ed`, `#F87171`, `#7F1D1D`
- These are semantic so can stay, but check they read well on light backgrounds

**3. `frontend/admin/customers.html`** (~12 hardcoded colors)
- Minimal changes needed

**4. `frontend/admin/vendors.html`** (~21 hardcoded colors)
- Role badges have specific colors — these are semantic and can stay
- Search bar and pagination colors

### Medium effort:

**5. `frontend/admin/settings.html`** (~28 hardcoded colors)
- Settings grid and checkbox colors
- Important: this is where the theme toggle UI will go (Part 6), so make sure the settings page itself themes correctly first

**6. `frontend/admin/studio.html`** (~30 hardcoded colors)
- Calendar and event colors: `#C06060`, `#F59E0B`, `#22C55E`
- Modal overlay background: `rgba(0,0,0,0.7)` → can stay
- Booth status colors

**7. `frontend/admin/rent.html`** (~41 hardcoded colors)
- Rent status colors (paid/unpaid/partial)
- Flag button colors
- Record payment modal

**8. `frontend/admin/payouts.html`** (~35 hardcoded colors)
- Payout status badges: `#7BC4A0` (approved), `#e8c070` (pending), `#c87070` (rejected)
- Summary card colors

**9. `frontend/admin/index.html`** (~56 hardcoded colors, but 107 already use variables)
- Dashboard summary cards
- Chart colors (these may need to stay hardcoded for chart libraries)
- Activity feed items

**10. `frontend/admin/inventory-verify.html`** (~46 hardcoded colors)
- Progress bar colors
- Status badges: `.status-complete`, `.status-partial`, `.status-none`
- Modal overlay
- Action button colors (archive, delete, restore)

### Public page:

**11. `frontend/shop/index.html`** (~75 hardcoded colors)
- Product cards, cart drawer, checkout form
- This is public-facing — light mode might actually be better as default here
- Add a light theme override if needed

---

## Color mapping reference (same as Part 3)

| Hardcoded color | Replace with |
|----------------|-------------|
| `#38383B`, `#2A2825`, `#1e1e20` | `var(--bg)` |
| `#44444A`, `#353230` | `var(--surface)` |
| `#4e4e54`, `#3E3B38` | `var(--surface-2)` |
| `#555558`, `#4A4643` | `var(--border)` |
| `rgba(201,169,110,0.22)`, `rgba(201,168,76,0.25)` | `var(--warm-border)` |
| `#F0EDE8`, `#F5F0E8` | `var(--text)` |
| `#A8A6A1`, `#B5AFA5` | `var(--text-light)` |
| `#8A847A` | `var(--text-muted)` |
| `#C9A96E`, `#C9A84C` | `var(--gold)` |
| `#9E8339` | `var(--gold-dim)` |
| `rgba(201,169,110,0.12)` | `var(--gold-glow)` |
| `#1a1a1d` (text on gold) | Keep as-is |
| Status reds, greens, ambers | Keep hardcoded or use `var(--danger)`, `var(--success)`, `var(--warning)` |

---

## Important notes

- **Work through files in order** — start with the easy ones
- **Verify dark theme is unchanged** after refactoring each file
- **Status/semantic colors** that use both a background AND text color (like badges) need both to be checked for contrast in light mode. If a red badge text doesn't read well on a white background, add a `[data-theme="light"]` override.
- For `rgba()` values that create subtle overlays on dark backgrounds, they may need different opacity in light mode. Add `[data-theme="light"]` overrides in the page's `<style>` block for these cases.

Commit and push when done.
