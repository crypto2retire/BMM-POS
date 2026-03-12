import os
import uuid
import io
from datetime import date, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, UploadFile, File
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image as PILImage

from app.database import get_db
from app.models.studio_class import StudioClass
from app.models.studio_image import StudioImage
from app.models.class_registration import ClassRegistration
from app.models.vendor import Vendor
from app.routers.auth import get_current_user
from app.schemas.class_registration import ClassRegistrationCreate, ClassRegistrationResponse

STUDIO_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "static", "images", "studio")
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 1200

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

    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    try:
        from PIL import ImageOps
        img = PILImage.open(io.BytesIO(contents))
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            ratio = MAX_IMAGE_DIMENSION / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        jpeg_bytes = buf.getvalue()
    except Exception:
        jpeg_bytes = contents

    os.makedirs(STUDIO_UPLOAD_DIR, exist_ok=True)
    filename = f"class_{class_id}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(STUDIO_UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(jpeg_bytes)

    existing = await db.execute(
        select(StudioImage).where(StudioImage.class_id == class_id)
    )
    old_img = existing.scalar_one_or_none()
    if old_img:
        old_img.image_data = jpeg_bytes
        old_img.content_type = "image/jpeg"
    else:
        db.add(StudioImage(class_id=class_id, image_data=jpeg_bytes, content_type="image/jpeg"))

    c.image_url = f"/api/v1/studio/classes/{class_id}/image"
    await db.commit()
    await db.refresh(c)
    return _class_to_response(c)


@router.get("/classes/{class_id}/image")
async def get_class_image(
    class_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StudioImage).where(StudioImage.class_id == class_id)
    )
    img = result.scalar_one_or_none()
    if img:
        return Response(content=img.image_data, media_type=img.content_type,
                        headers={"Cache-Control": "public, max-age=86400"})

    for fname in os.listdir(STUDIO_UPLOAD_DIR) if os.path.isdir(STUDIO_UPLOAD_DIR) else []:
        if fname.startswith(f"class_{class_id}_"):
            fpath = os.path.join(STUDIO_UPLOAD_DIR, fname)
            with open(fpath, "rb") as f:
                data = f.read()
            ct = "image/jpeg" if fname.endswith(".jpg") else "image/png"
            return Response(content=data, media_type=ct,
                            headers={"Cache-Control": "public, max-age=86400"})

    raise HTTPException(status_code=404, detail="Image not found")


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

    img_result = await db.execute(
        select(StudioImage).where(StudioImage.class_id == class_id)
    )
    old_img = img_result.scalar_one_or_none()
    if old_img:
        await db.delete(old_img)

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


@router.post("/classes/{class_id}/register", status_code=status.HTTP_201_CREATED)
async def register_for_class(
    class_id: int,
    data: ClassRegistrationCreate,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import with_for_update
    result = await db.execute(
        select(StudioClass).where(
            StudioClass.id == class_id,
            StudioClass.is_published == True,
            StudioClass.is_cancelled == False,
        ).with_for_update()
    )
    cls = result.scalar_one_or_none()
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found or not available")

    if cls.class_date < date.today():
        raise HTTPException(status_code=400, detail="This class has already passed")

    if data.num_spots < 1 or data.num_spots > 10:
        raise HTTPException(status_code=400, detail="Must register for 1–10 spots")

    spots_left = cls.capacity - cls.enrolled
    if data.num_spots > spots_left:
        raise HTTPException(
            status_code=400,
            detail=f"Only {spots_left} spot(s) remaining"
        )

    existing = await db.execute(
        select(ClassRegistration).where(
            ClassRegistration.class_id == class_id,
            ClassRegistration.customer_email == data.customer_email.strip().lower(),
            ClassRegistration.status == "confirmed",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="You are already registered for this class")

    reg = ClassRegistration(
        class_id=class_id,
        customer_name=data.customer_name.strip(),
        customer_email=data.customer_email.strip().lower(),
        customer_phone=data.customer_phone.strip() if data.customer_phone else None,
        num_spots=data.num_spots,
        notes=data.notes,
        status="confirmed",
    )
    db.add(reg)

    cls.enrolled += data.num_spots
    await db.commit()
    await db.refresh(reg)
    return ClassRegistrationResponse.model_validate(reg)


@router.get("/classes/{class_id}/registrations")
async def list_registrations(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(
        select(ClassRegistration)
        .where(ClassRegistration.class_id == class_id)
        .order_by(ClassRegistration.created_at)
    )
    regs = result.scalars().all()
    return [ClassRegistrationResponse.model_validate(r) for r in regs]


@router.delete("/registrations/{reg_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_registration(
    reg_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin", "cashier"):
        raise HTTPException(status_code=403, detail="Admin or cashier access required")

    result = await db.execute(
        select(ClassRegistration).where(ClassRegistration.id == reg_id)
    )
    reg = result.scalar_one_or_none()
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")

    if reg.status == "cancelled":
        raise HTTPException(status_code=400, detail="Already cancelled")

    cls_result = await db.execute(
        select(StudioClass).where(StudioClass.id == reg.class_id)
    )
    cls = cls_result.scalar_one_or_none()
    if cls:
        cls.enrolled = max(0, cls.enrolled - reg.num_spots)

    reg.status = "cancelled"
    await db.commit()
