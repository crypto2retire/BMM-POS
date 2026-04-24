import os
import uuid
import io
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, UploadFile, File
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from PIL import Image as PILImage

from app.database import get_db
from app.models.studio_class import StudioClass
from app.models.studio_image import StudioImage
from app.models.class_registration import ClassRegistration
from app.models.vendor import Vendor
from app.routers.auth import get_current_user, get_user_from_token
from app.routers.settings import role_feature_allowed, require_staff_feature
from app.schemas.class_registration import ClassRegistrationCreate, ClassRegistrationResponse
from app.services import spaces as spaces_svc
from app.services.square import create_payment_link

STUDIO_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "static", "images", "studio")
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_IMAGE_DIMENSION = 1200
CLASS_PAYMENT_HOLD_MINUTES = 20

router = APIRouter(prefix="/studio", tags=["studio"])

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Optional[Vendor]:
    if not token:
        return None
    try:
        return await get_user_from_token(token, db)
    except Exception:
        return None


async def _can_manage_or_host_class(
    db: AsyncSession,
    current_user: Vendor,
    class_id: int,
) -> tuple[bool, Optional[StudioClass]]:
    class_result = await db.execute(select(StudioClass).where(StudioClass.id == class_id))
    studio_class = class_result.scalar_one_or_none()
    if not studio_class:
        return False, None

    if current_user.role in ("admin", "cashier"):
        if await role_feature_allowed(db, current_user, "role_manage_studio"):
            return True, studio_class

    if studio_class.created_by and studio_class.created_by == current_user.id:
        return True, studio_class

    return False, studio_class


def _normalize_email(email: str) -> str:
    return str(email).strip().lower()


async def _release_expired_pending_registrations(
    db: AsyncSession,
    class_ids: Optional[list[int]] = None,
) -> int:
    now = datetime.now(timezone.utc)
    query = select(ClassRegistration).where(
        ClassRegistration.status == "pending",
        ClassRegistration.pending_expires_at.is_not(None),
        ClassRegistration.pending_expires_at <= now,
    )
    if class_ids:
        query = query.where(ClassRegistration.class_id.in_(class_ids))

    expired_regs = (await db.execute(query)).scalars().all()
    if not expired_regs:
        return 0

    affected_class_ids = sorted({reg.class_id for reg in expired_regs})
    class_rows = (
        await db.execute(
            select(StudioClass)
            .where(StudioClass.id.in_(affected_class_ids))
            .with_for_update()
        )
    ).scalars().all()
    class_map = {row.id: row for row in class_rows}

    released = 0
    for reg in expired_regs:
        studio_class = class_map.get(reg.class_id)
        if studio_class:
            current_enrolled = int(studio_class.enrolled or 0)
            studio_class.enrolled = max(0, current_enrolled - int(reg.num_spots or 0))
        reg.status = "expired"
        reg.pending_expires_at = None
        released += 1

    await db.commit()
    return released


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
        created_by=c.created_by,
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
    await _release_expired_pending_registrations(db)
    q = select(StudioClass).order_by(StudioClass.class_date, StudioClass.start_time)

    is_staff = current_user and current_user.role in ("admin", "cashier")
    can_manage_studio = False
    if is_staff and current_user:
        can_manage_studio = await role_feature_allowed(db, current_user, "role_manage_studio")

    if not published_only and can_manage_studio:
        pass
    elif not published_only and current_user:
        q = q.where(StudioClass.created_by == current_user.id)
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
    await _release_expired_pending_registrations(db, [class_id])
    q = select(StudioClass).where(StudioClass.id == class_id)
    is_staff = current_user and current_user.role in ("admin", "cashier")
    can_manage_studio = False
    if is_staff and current_user:
        can_manage_studio = await role_feature_allowed(db, current_user, "role_manage_studio")
    if can_manage_studio:
        pass
    elif current_user:
        q = q.where(or_(StudioClass.is_published == True, StudioClass.created_by == current_user.id))
    else:
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_studio")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_studio")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_studio")),
):
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_studio")),
):
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

    # Validate actual file content matches declared image type
    ext = os.path.splitext(file.filename or "photo.jpg")[1].lower()
    declared_type = file.content_type or "application/octet-stream"
    from app.services.upload_security import _validate_image_content
    try:
        _validate_image_content(contents, declared_type)
    except HTTPException:
        ext_to_mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
        detected_mime = ext_to_mime.get(ext)
        if detected_mime:
            _validate_image_content(contents, detected_mime)
        else:
            raise

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

    filename = f"class_{class_id}_{uuid.uuid4().hex[:8]}.jpg"
    spaces_key = f"studio/{filename}"
    cdn_url = spaces_svc.upload_bytes(jpeg_bytes, spaces_key, "image/jpeg")
    if cdn_url:
        image_url = cdn_url
    else:
        from app.services.upload_security import save_upload
        save_upload(STUDIO_UPLOAD_DIR, filename, jpeg_bytes)
        image_url = f"/static/images/studio/{filename}"

    existing = await db.execute(
        select(StudioImage).where(StudioImage.class_id == class_id)
    )
    old_img = existing.scalar_one_or_none()
    if old_img:
        old_img.image_data = jpeg_bytes
        old_img.content_type = "image/jpeg"
    else:
        db.add(StudioImage(class_id=class_id, image_data=jpeg_bytes, content_type="image/jpeg"))

    c.image_url = image_url
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
    current_user: Vendor = Depends(require_staff_feature("role_manage_studio")),
):
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
        if c.image_url.startswith("http"):
            spaces_svc.delete_object(c.image_url)
        else:
            old_file = os.path.join(STUDIO_UPLOAD_DIR, os.path.basename(c.image_url))
            if os.path.exists(old_file):
                os.remove(old_file)
        c.image_url = None

    await db.commit()
    return {"detail": "Image removed"}


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    await _release_expired_pending_registrations(db)
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
    await _release_expired_pending_registrations(db, [class_id])
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

    normalized_email = _normalize_email(data.customer_email)
    enrolled = int(cls.enrolled or 0)
    capacity = int(cls.capacity or 0)
    spots_left = max(0, capacity - enrolled)
    if data.num_spots > spots_left:
        raise HTTPException(
            status_code=400,
            detail=f"Only {spots_left} spot(s) remaining"
        )

    existing = await db.execute(
        select(ClassRegistration).where(
            ClassRegistration.class_id == class_id,
            ClassRegistration.customer_email == normalized_email,
            ClassRegistration.status == "confirmed",
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="You are already registered for this class")

    reg = ClassRegistration(
        class_id=class_id,
        customer_name=data.customer_name,
        customer_email=normalized_email,
        customer_phone=data.customer_phone,
        num_spots=data.num_spots,
        notes=data.notes,
        status="confirmed",
    )
    db.add(reg)
    cls.enrolled = enrolled + data.num_spots
    try:
        await db.flush()
        reg_id = reg.id
        reg_created_at = reg.created_at or datetime.now(timezone.utc)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Unable to save this registration")
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Unable to save this registration right now")
    return {
        "id": reg_id,
        "class_id": class_id,
        "customer_name": data.customer_name,
        "customer_email": normalized_email,
        "customer_phone": data.customer_phone,
        "num_spots": reg.num_spots,
        "notes": data.notes,
        "status": "confirmed",
        "created_at": reg_created_at,
    }


@router.post("/classes/{class_id}/create-payment")
async def create_class_payment(
    class_id: int,
    data: ClassRegistrationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
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

    normalized_email = _normalize_email(data.customer_email)
    existing = await db.execute(
        select(ClassRegistration).where(
            ClassRegistration.class_id == class_id,
            ClassRegistration.customer_email == normalized_email,
            ClassRegistration.status.in_(("confirmed", "pending")),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This email already has a signup in progress for this class")

    enrolled = int(cls.enrolled or 0)
    capacity = int(cls.capacity or 0)
    spots_left = max(0, capacity - enrolled)
    if data.num_spots > spots_left:
        raise HTTPException(status_code=400, detail=f"Only {spots_left} spot(s) remaining")

    registration = ClassRegistration(
        class_id=class_id,
        customer_name=data.customer_name,
        customer_email=normalized_email,
        customer_phone=data.customer_phone,
        num_spots=data.num_spots,
        notes=data.notes,
        status="pending",
        pending_expires_at=datetime.now(timezone.utc) + timedelta(minutes=CLASS_PAYMENT_HOLD_MINUTES),
    )
    db.add(registration)
    cls.enrolled = enrolled + data.num_spots
    await db.flush()

    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    scheme = request.headers.get("x-forwarded-proto") or "https"
    base_url = f"{scheme}://{host}"
    redirect_url = f"{base_url}/shop/classes.html?class_payment=success&ref={registration.public_id}"

    try:
        total = (Decimal(str(cls.price)) * Decimal(str(data.num_spots))).quantize(Decimal("0.01"), ROUND_HALF_UP)
        link_result = await create_payment_link(
            name=f"Class Signup: {cls.title[:80]}",
            price_cents=int(total * 100),
            redirect_url=redirect_url,
        )
        registration.square_payment_id = link_result.get("payment_link_id", "")
        await db.commit()
        return {
            "reference_id": registration.public_id,
            "payment_url": link_result["url"],
            "total": float(total),
            "message": "Redirecting to secure checkout...",
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Unable to start class checkout right now")


class ConfirmClassPaymentRequest(BaseModel):
    reference_id: str


@router.post("/classes/payment-confirmed")
async def confirm_class_payment(
    req: ConfirmClassPaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _ = request
    await _release_expired_pending_registrations(db)
    reference_id = (req.reference_id or "").strip()
    if not reference_id:
        raise HTTPException(status_code=400, detail="Registration reference is required")

    result = await db.execute(
        select(ClassRegistration).where(ClassRegistration.public_id == reference_id)
    )
    reg = result.scalar_one_or_none()
    if not reg:
        raise HTTPException(status_code=404, detail="Class registration not found")
    if reg.status == "confirmed":
        return {"message": "Payment already confirmed."}
    if reg.status != "pending":
        raise HTTPException(status_code=400, detail="This class signup is not awaiting payment")

    reg.status = "confirmed"
    reg.pending_expires_at = None
    await db.commit()
    return {"message": "Payment confirmed. Your class signup is complete."}


@router.get("/classes/{class_id}/registrations")
async def list_registrations(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    await _release_expired_pending_registrations(db, [class_id])
    allowed, studio_class = await _can_manage_or_host_class(db, current_user, class_id)
    if not studio_class:
        raise HTTPException(status_code=404, detail="Class not found")
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

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
    if current_user.role in ("admin", "cashier"):
        if not await role_feature_allowed(db, current_user, "role_manage_studio"):
            raise HTTPException(status_code=403, detail="Access denied")
    elif not cls or cls.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if cls:
        cls.enrolled = max(0, cls.enrolled - reg.num_spots)

    reg.status = "cancelled"
    await db.commit()
