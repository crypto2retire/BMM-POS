# Task: Fix Void Confirmation Modal Hidden Behind Receipt

## Problem
When clicking "Void This Sale" from the receipt modal, the void confirmation popup opens BEHIND the receipt because its z-index (450) is lower than the receipt modal's z-index (1000 from `.pos-modal-overlay`).

## Fix

### File: `frontend/pos/index.html`

Find (around line 1178):

```html
<div class="pos-modal-overlay hidden" id="void-confirm-modal" style="z-index:450">
```

**Replace with:**

```html
<div class="pos-modal-overlay hidden" id="void-confirm-modal" style="z-index:1100">
```

That's it — one number change. The void modal needs to be ABOVE the receipt modal (z-index 1000) and the receipt detail modal (also 1000). Setting it to 1100 puts it on top of any other modal it might be launched from.

## Testing
1. Make a sale (cash or card)
2. On the receipt modal, click "Void This Sale"
3. Verify the void confirmation popup appears ON TOP of the receipt — you should see the red "⚠ Void Sale" heading, reason input, and Confirm/Cancel buttons
4. Cancel the void — receipt should still be visible underneath
5. Also test voiding from the receipt lookup (the other Void button) — same behavior expected

## One file changed
- `frontend/pos/index.html` (one inline style attribute)
