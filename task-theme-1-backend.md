# Task: Light/Dark Mode + Font Size — Part 1: Backend

Add per-user theme and font size preferences stored in the database.

---

## Step 1: Add columns to Vendor model

File: `app/models/vendor.py`

Add after `notes` (around line 32):

```python
    theme_preference: Mapped[str] = mapped_column(String(10), default="dark", nullable=False, server_default="dark")
    font_size_preference: Mapped[str] = mapped_column(String(10), default="medium", nullable=False, server_default="medium")
```

---

## Step 2: Auto-create columns on startup

File: `app/main.py`

Add inside the lifespan startup block alongside the other ALTER TABLE statements:

```python
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "theme_preference VARCHAR(10) NOT NULL DEFAULT 'dark'"
            ))
            await session.execute(text(
                "ALTER TABLE vendors ADD COLUMN IF NOT EXISTS "
                "font_size_preference VARCHAR(10) NOT NULL DEFAULT 'medium'"
            ))
```

---

## Step 3: Add preferences to the /me endpoint response

File: `app/routers/auth.py`

Find the `get_me` (or `get_current_user_info`) endpoint that returns user data. Add `theme_preference` and `font_size_preference` to its response:

```python
@router.get("/me")
async def get_me(current_user: Vendor = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "theme_preference": current_user.theme_preference,
        "font_size_preference": current_user.font_size_preference,
    }
```

---

## Step 4: Add endpoint to update preferences

File: `app/routers/auth.py`

Add a new endpoint for updating display preferences. This should be accessible to ALL authenticated users (admin, cashier, vendor):

```python
from pydantic import BaseModel
from typing import Optional

class DisplayPreferencesUpdate(BaseModel):
    theme_preference: Optional[str] = None
    font_size_preference: Optional[str] = None

@router.put("/me/preferences")
async def update_preferences(
    prefs: DisplayPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    """Update the current user's display preferences."""
    valid_themes = {"dark", "light"}
    valid_font_sizes = {"small", "medium", "large"}

    if prefs.theme_preference is not None:
        if prefs.theme_preference not in valid_themes:
            raise HTTPException(status_code=400, detail=f"Invalid theme. Must be one of: {valid_themes}")
        current_user.theme_preference = prefs.theme_preference

    if prefs.font_size_preference is not None:
        if prefs.font_size_preference not in valid_font_sizes:
            raise HTTPException(status_code=400, detail=f"Invalid font size. Must be one of: {valid_font_sizes}")
        current_user.font_size_preference = prefs.font_size_preference

    await db.commit()

    return {
        "theme_preference": current_user.theme_preference,
        "font_size_preference": current_user.font_size_preference,
        "detail": "Preferences updated.",
    }
```

Make sure to import `get_db` and `AsyncSession` at the top of auth.py if not already imported:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
```

---

## Step 5: Add preferences to vendor schema responses (optional but recommended)

File: `app/schemas/vendor.py`

If there's a `VendorResponse` schema, add:

```python
    theme_preference: Optional[str] = "dark"
    font_size_preference: Optional[str] = "medium"
```

---

## Summary

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/auth/me` | GET | Returns user info including theme + font size |
| `/api/v1/auth/me/preferences` | PUT | Update theme and/or font size preference |

Valid values:
- `theme_preference`: `"dark"` (default), `"light"`
- `font_size_preference`: `"small"` (14px base), `"medium"` (16px base, default), `"large"` (18px base)

Commit and push when done.
