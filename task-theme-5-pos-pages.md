# Task: Light/Dark Mode — Part 5: POS Page Color Refactoring

Convert hardcoded colors in POS pages to CSS variables. **This is the hardest task** — pos/index.html has ~468 hardcoded color instances.

**Prerequisite:** Parts 1-4 must be deployed. Run this LAST.

---

## Strategy

Same color mapping as Parts 3-4. Use the reference table from `task-theme-3-vendor-pages.md`.

**Because of the volume (~468 instances in pos/index.html alone), work methodically:**

1. Start with the `<style>` block — convert all colors there first
2. Then tackle inline `style=` attributes in the HTML
3. Then JavaScript-generated styles
4. Finally, test in both themes

---

## Files to update

### 1. `frontend/pos/index.html` (~468 hardcoded colors)

This is the main POS terminal. Major color areas:

**Style block colors:**
- Cart area backgrounds and borders
- Payment method buttons (cash, card, gift card — each has unique colors)
- Modal backgrounds and overlays
- Status indicators (sale complete, error, processing)
- Quick-action button grid
- Receipt styling

**Inline style colors (the biggest problem):**
- Many elements use `style="background: #xxx; color: #yyy; border: 1px solid #zzz"` inline
- These all need converting to CSS variable references
- Some are in dynamically generated HTML in JavaScript template literals

**JavaScript-generated colors:**
- Cart item rows generated with inline colors
- Payment status messages
- Alert/toast messages
- The POS has complex state-driven UI where colors change based on transaction state

**Special considerations:**
- Payment method buttons have distinctive colors (green for cash, blue for card, purple for gift card) — these are functional indicators. Keep the hue but make sure they have enough contrast in light mode. Add `[data-theme="light"]` overrides in the style block if needed.
- The receipt area often uses `#fff` background with dark text — this actually works well in both themes, but the surrounding area needs to adapt.
- Modal overlays (`rgba(0,0,0,0.6)`) can stay as-is — they work in both themes.

### 2. `frontend/pos/register.html` (~99 hardcoded colors)

The cash register / payment completion screen:

**Focus areas:**
- Receipt card (white background with dark text — may need minimal changes)
- Denomination button grid
- Change calculation display
- Payment summary colors

---

## Color mapping reference (same as Parts 3-4)

| Hardcoded color | Replace with |
|----------------|-------------|
| `#38383B`, `#2A2825`, `#1e1e20` | `var(--bg)` |
| `#44444A`, `#353230` | `var(--surface)` |
| `#4e4e54`, `#3E3B38` | `var(--surface-2)` |
| `#555558`, `#4A4643` | `var(--border)` |
| `rgba(201,169,110,0.22)` | `var(--warm-border)` |
| `#F0EDE8`, `#F5F0E8` | `var(--text)` |
| `#A8A6A1`, `#B5AFA5` | `var(--text-light)` |
| `#C9A96E`, `#C9A84C` | `var(--gold)` |
| `#1a1a1d` (text on gold) | Keep as-is |

**Additional POS-specific colors to map:**
| Color | Current use | Light mode handling |
|-------|------------|-------------------|
| `#EF4444` | Error/cancel | Keep — reads fine on white |
| `#22C55E`, `#065F46` | Success/complete | Keep or use `var(--success)` |
| `#F59E0B`, `#92400E` | Warning/pending | Keep or use `var(--warning)` |
| `#7C3AED` | Gift card | Keep — distinctive enough |
| `#0E7490` | Card payment | Keep or use `var(--info)` |
| `#6EE7B7` | Light green accents | Add light mode override if low contrast |
| `#FDE68A` | Light amber accents | May need override — low contrast on white |

---

## Important notes

- **This is ~570 color changes across 2 files.** Take it section by section.
- **POS is used by cashiers all day** — test thoroughly in both themes
- **Receipt display** should probably stay as-is (white background, dark text) regardless of theme
- **The quick cash buttons and denomination grid** need to be clearly readable in both themes — test these specifically
- **Do NOT change** the dark theme appearance. After refactoring, dark mode should look identical to before.
- If any payment method colors don't read well in light mode, add specific `[data-theme="light"] .payment-cash { ... }` overrides in the style block.

Commit and push when done.
