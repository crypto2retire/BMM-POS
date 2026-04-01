# Task: Fix Vendor Notes Not Saving

## Problem
The admin vendors page (`frontend/admin/vendors.html`) has a "Notes" textarea for internal notes about vendors. The frontend sends `notes` in the update payload, but the backend has no `notes` column on the vendor model, no `notes` field in the schemas, so the data is silently dropped by Pydantic. Notes never save.

## Files to edit

### 1. `app/models/vendor.py` — Add notes column to Vendor model

Add this field to the `Vendor` class (after `assistant_name` or wherever makes sense):

```python
notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

`Text` is already imported at the top of the file.

### 2. `app/main.py` — Auto-create column on startup

Add a column check in the lifespan startup (same pattern as existing auto column creation) for `vendors.notes` (type TEXT, nullable). This ensures the column gets added to the existing database without a migration.

### 3. `app/schemas/vendor.py` — Add notes to all three vendor schemas

In `VendorUpdate`, add:
```python
notes: Optional[str] = None
```

In `VendorResponse`, add:
```python
notes: Optional[str] = None
```

In `VendorCreate`, optionally add (not required but nice to have):
```python
notes: Optional[str] = None
```

### 4. No frontend changes needed

The frontend already:
- Has the textarea at line ~426: `<textarea class="form-control" id="e-notes">`
- Populates it on edit at line ~787: `document.getElementById('e-notes').value = v.notes || '';`
- Sends it in the update body at line ~847: `notes: document.getElementById('e-notes').value || null,`

So once the backend accepts and stores the `notes` field, everything will work.

## Test
1. Open admin vendors page, edit a vendor
2. Type something in the Notes field
3. Click Save/Update
4. Close the edit panel, reopen the same vendor — notes should still be there
5. Edit notes again, save — should update
6. Clear notes, save — should clear (null)
7. Commit and push to main
