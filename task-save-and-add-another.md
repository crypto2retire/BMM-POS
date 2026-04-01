# Task: Add "Save & Add Another" Option When Creating Items

## Problem
When adding new items on the vendor items page (`frontend/vendor/items.html`), the modal closes after saving. If adding multiple items, the user has to reopen the modal each time. There should be a choice to add another item or save and close.

## File to edit
`frontend/vendor/items.html`

## What to change

### Step 1 — Update the modal footer buttons

Find the modal footer (around line ~573):
```html
<div class="modal-footer">
    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
    <button class="btn btn-primary btn-lg" onclick="saveItem()" id="save-btn">Save Item</button>
</div>
```

Replace with:
```html
<div class="modal-footer">
    <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
    <button class="btn btn-primary" onclick="saveItem(false)" id="save-close-btn" style="display:none">Save & Close</button>
    <button class="btn btn-primary" onclick="saveItem(true)" id="save-another-btn" style="display:none">Save & Add Another</button>
    <button class="btn btn-primary btn-lg" onclick="saveItem(false)" id="save-btn">Save Item</button>
</div>
```

- `save-btn` is the single button shown when EDITING an existing item (same as before)
- `save-close-btn` and `save-another-btn` are shown when ADDING a new item
- `save-btn` is hidden when adding

### Step 2 — Toggle button visibility in openModal()

In `openModal()` (around line ~1027), after setting the modal title, add logic to show/hide the right buttons:

```javascript
// Show appropriate save buttons
if (item) {
    // Editing — show single Save button
    document.getElementById('save-btn').style.display = '';
    document.getElementById('save-close-btn').style.display = 'none';
    document.getElementById('save-another-btn').style.display = 'none';
} else {
    // Adding — show Save & Close + Save & Add Another
    document.getElementById('save-btn').style.display = 'none';
    document.getElementById('save-close-btn').style.display = '';
    document.getElementById('save-another-btn').style.display = '';
}
```

### Step 3 — Update saveItem() to accept a parameter

Change `saveItem()` signature (around line ~1344) to accept a `addAnother` parameter:

```javascript
async function saveItem(addAnother = false) {
```

### Step 4 — Change post-save behavior

In `saveItem()`, find where it calls `closeModal()` after a successful save (around line ~1418). Replace that section with:

```javascript
if (!editingId && addAnother) {
    // Clear the form for another item but keep the modal open
    document.getElementById('f-name').value = '';
    document.getElementById('f-price').value = '';
    document.getElementById('f-quantity').value = '1';
    document.getElementById('f-description').value = '';
    document.getElementById('f-sale-price').value = '';
    document.getElementById('f-sale-start').value = '';
    document.getElementById('f-sale-end').value = '';
    document.getElementById('f-is-online').checked = false;
    document.getElementById('f-is-tax-exempt').checked = false;
    document.getElementById('f-is-consignment').checked = false;
    document.getElementById('f-consignment-rate').value = '';
    document.getElementById('consignment-rate-group').style.display = 'none';
    // Keep vendor selection and category as-is (likely same for batch entry)
    // Clear photo
    pendingPhotoFile = null;
    pendingPhotoBase64 = null;
    pendingPhotoMime = null;
    var preview = document.getElementById('photo-preview');
    if (preview) preview.innerHTML = '';
    // Clear modal alert and show success
    document.getElementById('modal-alert').innerHTML = '';
    showAlert('modal-alert', 'Item saved! Add another below.', 'success');
    // Focus the name field for quick entry
    document.getElementById('f-name').focus();
    // Reload item list in background
    await loadItems();
} else {
    closeModal();
    await loadItems();
}
```

Note: Keep the category and vendor dropdown values when adding another — the user is likely adding multiple items for the same vendor in the same category.

### Step 5 — Update button text during save

The save process currently changes `save-btn` text to "Saving…". Update this to also handle the new buttons. In `saveItem()`, find where it does:
```javascript
const btn = document.getElementById('save-btn');
btn.disabled = true;
btn.textContent = 'Saving…';
```

Replace with:
```javascript
const btn = addAnother ? document.getElementById('save-another-btn') : (editingId ? document.getElementById('save-btn') : document.getElementById('save-close-btn'));
const otherBtn = addAnother ? document.getElementById('save-close-btn') : document.getElementById('save-another-btn');
btn.disabled = true;
if (otherBtn) otherBtn.disabled = true;
btn.textContent = 'Saving…';
```

And in the `finally` block, restore both buttons:
```javascript
btn.disabled = false;
btn.textContent = addAnother ? 'Save & Add Another' : (editingId ? 'Save Item' : 'Save & Close');
if (otherBtn) {
    otherBtn.disabled = false;
    otherBtn.textContent = addAnother ? 'Save & Close' : 'Save & Add Another';
}
```

## Design notes
- Both buttons should use the same `btn btn-primary` style
- "Save & Add Another" could optionally have a slightly different accent (e.g. the gold color) to make it stand out as the "keep going" action
- When editing, only the single "Save Item" button appears (no "Add Another" for edits)

## Test
1. Click "Add Item" — modal should show "Save & Close" and "Save & Add Another" buttons
2. Fill in item, click "Save & Add Another" — item saves, form clears (except vendor/category), name field focused, success message shows in modal
3. Fill in another item, click "Save & Close" — item saves, modal closes, list refreshes
4. Edit an existing item — only "Save Item" button appears (same as before)
5. Commit and push to main
