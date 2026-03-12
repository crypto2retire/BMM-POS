import os
import uuid
from datetime import date, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, UploadFile, File
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.studio_class import StudioClass
from app.models.vendor import Vendor
from app.routers.auth import get_current_user

STUDIO_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "static", "images", "studio")

router = APIRouter(prefix="/studio", tags=["studio"])

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Optional[Vendor]:
    if not token:
        return None
    try:
        from jose import jwt
        from app.config import settings
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        email = payload.get("sub")
        if not email:
            return None
        result = await db.execute(select(Vendor).where(Vendor.email == email))
        return result.scalar_one_or_none()
    except Exception:
        return None


def _class_to_response(c: StudioClass) -> "StudioClassResponse":
    from app.schemas.studio_class import StudioClassResponse
    return StudioClassResponse(
        id=c.id,
        title=c.title,
        description=c.description,
        instructor=c.instructor,
        class_date=c.class_date,
        start_time=c.start_time,
        end_time=c.end_time,
        capacity=c.capacity,
        enrolled=c.enrolled,
        price=c.price,
        category=c.category,
        location=c.location,
        is_published=c.is_published,
        is_cancelled=c.is_cancelled,
        image_url=c.image_url,
        created_at=c.created_at,
        spots_left=max(0, c.capacity - c.enrolled),
    )


@router.get("/classes")
async def list_classes(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    category: Optional[str] = Query(None),
    published_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[Vendor] = Depends(get_optional_user),
):
    q = select(StudioClass).order_by(StudioClass.class_date, StudioClass.start_time)

    is_staff = current_user and current_user.role in ("admin", "cashier")

    if not published_only and is_staff:
        pass
    else:
        q = q.where(StudioClass.is_published == True)

    if start:
        q = q.where(StudioClass.class_date >= start)
    else:
        q = q.where(StudioClass.class_date >= date.today())

    if end:
        q = q.where(StudioClass.class_date <= end)

    if category:
        q = q.where(StudioClass.category == category)

    result = await db.execute(q)
    classes = result.scalars().all()
    return [_class_to_response(c) for c in classes]


@router.get("/classes/{class_id}")
async def get_class(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[Vendor] = Depends(get_optional_user),
):
    q = select(StudioClass).where(StudioClass.id == class_id)
    is_staff = current_user and current_user.role in ("admin", "cashier")
    if not is_staff:
        q = q.where(StudioClass.is_published == True)

    result = await db.execute(q)
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Class not found")
    return _class_to_response(c)


@router.post("/classes", status_code=status.HTTP_201_CREATED)
async def create_class(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    from app.schemas.studio_class import StudioClassCreate
    parsed = StudioClassCreate(**data)

    c = StudioClass(
        title=parsed.title,
        description=parsed.description,
        instructor=parsed.instructor,
        class_date=parsed.class_date,
        start_time=parsed.start_time,
        end_time=parsed.end_time,
        capacity=parsed.capacity,
        price=parsed.price,
        category=parsed.category,
        location=parsed.location or "Studio",
        is_published=parsed.is_published,
        is_cancelled=data.get("is_cancelled", False),
        image_url=parsed.image_url,
        created_by=current_user.id,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return _class_to_response(c)


@router.put("/classes/{class_id}")
async def update_class(
    class_id: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(select(StudioClass).where(StudioClass.id == class_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Class not found")

    from app.schemas.studio_class import StudioClassUpdate
    parsed = StudioClassUpdate(**data)
    update_data = parsed.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(c, field, value)

    await db.commit()
    await db.refresh(c)
    return _class_to_response(c)


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(select(StudioClass).where(StudioClass.id == class_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Class not found")

    await db.delete(c)
    await db.commit()


@router.post("/classes/{class_id}/image")
async def upload_class_image(
    class_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(select(StudioClass).where(StudioClass.id == class_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Class not found")

    allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    ext = os.path.splitext(file.filename or "photo.jpg")[1].lower() or ".jpg"
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    os.makedirs(STUDIO_UPLOAD_DIR, exist_ok=True)

    if c.image_url:
        old_file = os.path.join(STUDIO_UPLOAD_DIR, os.path.basename(c.image_url))
        if os.path.exists(old_file):
            os.remove(old_file)

    filename = f"class_{class_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(STUDIO_UPLOAD_DIR, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    c.image_url = f"/static/images/studio/{filename}"
    await db.commit()
    await db.refresh(c)
    return _class_to_response(c)


@router.delete("/classes/{class_id}/image")
async def delete_class_image(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(select(StudioClass).where(StudioClass.id == class_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Class not found")

    if c.image_url:
        old_file = os.path.join(STUDIO_UPLOAD_DIR, os.path.basename(c.image_url))
        if os.path.exists(old_file):
            os.remove(old_file)
        c.image_url = None
        await db.commit()

    return {"detail": "Image removed"}


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(StudioClass.category)
        .where(StudioClass.category != None)
        .where(StudioClass.is_published == True)
        .distinct()
        .order_by(StudioClass.category)
    )
    return [row[0] for row in result.all()]
