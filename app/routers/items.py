import uuid
import os
import shutil
from decimal import Decimal
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Body, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload
from PIL import Image
import io
from app.database import get_db
from app.models.item import Item
from app.models.item_image import ItemImage
from app.models.item_variable import ItemVariable
from app.models.item_variant import ItemVariant
from app.models.vendor import Vendor
from app.models.sale import SaleItem
from app.services.audit import log_audit
from app.schemas.item import ItemCreate, ItemUpdate, ItemResponse, ItemListingResponse, VariantResponse
from app.routers.auth import get_current_user
from app.routers.settings import role_feature_allowed, get_setting
from app.services.barcode import generate_sku, generate_short_barcode, maybe_upgrade_barcode
from app.services.labels import generate_label_pdf, generate_label_pdf_batch
from app.services import spaces as spaces_svc
from app.models.store_setting import StoreSetting

PHOTO_UPLOAD_DIR = "frontend/static/images/items"
IMAGE_UPLOAD_DIR = "frontend/static/uploads/items"
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_DIMENSION = 800
MAX_ITEM_PHOTOS = 10

router = APIRouter(prefix="/items", tags=["items"])


async def _save_variables_and_variants(
    db: AsyncSession, item: Item, variables_data, variants_data
) -> None:
    """Save variable definitions and variant rows for an item."""
    # Clear existing
    await db.execute(
        select(ItemVariable).where(ItemVariable.item_id == item.id)
    )
    for v in list(item.variables or []):
        await db.delete(v)
    for v in list(item.variants or []):
        await db.delete(v)
    await db.flush()

    if variables_data:
        for idx, var_def in enumerate(variables_data[:2]):
            var = ItemVariable(
                item_id=item.id,
                name=var_def.name.strip(),
                position=idx,
                options=",".join([o.strip() for o in var_def.options if o.strip()]),
            )
            db.add(var)

    if variants_data:
        for v_in in variants_data:
            # Check barcode uniqueness
            if v_in.barcode:
                existing = await db.execute(
                    select(ItemVariant).where(ItemVariant.barcode == v_in.barcode)
                )
                if existing.scalar_one_or_none():
                    raise HTTPException(
                        status_code=400,
                        detail=f"Variant barcode '{v_in.barcode}' already exists",
                    )
            # Generate SKU if not provided
            variant_sku = v_in.sku
            if not variant_sku:
                variant_sku = f"{item.sku}-V{item.id}{len(item.variants or []) + 1}"

            variant = ItemVariant(
                item_id=item.id,
                sku=variant_sku,
                barcode=v_in.barcode,
                variable_1_value=v_in.variable_1_value,
                variable_2_value=v_in.variable_2_value,
                price=v_in.price,
                quantity=v_in.quantity,
                photo_url=v_in.photo_url,
                status="active",
            )
            db.add(variant)

    await db.flush()


def _parse_iso_date(value, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if not value or not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid date")


async def _require_manage_items(db: AsyncSession, user: Vendor) -> None:
    if not await role_feature_allowed(db, user, "role_manage_items"):
        raise HTTPException(
            status_code=403,
            detail="Item management is disabled for your role in Settings → User Roles.",
        )


async def _can_view_all_items(db: AsyncSession, user: Vendor) -> bool:
    if user.role == "admin":
        return True
    if user.role != "cashier":
        return False
    for feature in (
        "role_manage_items",
        "role_manage_vendors",
        "role_process_sales",
        "role_manage_rent",
        "role_view_reports",
    ):
        if await role_feature_allowed(db, user, feature):
            return True
    return False


async def _require_view_items(db: AsyncSession, user: Vendor) -> None:
    if user.role in ("admin", "cashier"):
        if await _can_view_all_items(db, user):
            return
        raise HTTPException(
            status_code=403,
            detail="Item viewing is not enabled for your role in Settings → User Roles.",
        )
    await _require_manage_items(db, user)


async def _can_reactivate_archived_items(db: AsyncSession, user: Vendor) -> bool:
    if user.role in ("admin", "cashier"):
        return await _can_view_all_items(db, user)
    return await role_feature_allowed(db, user, "role_manage_items")


def item_to_response(item: Item) -> ItemResponse:
    booth_number = None
    if item.vendor:
        booth_number = item.vendor.booth_number

    # Build variables list from loaded relationships
    variables_list = None
    if hasattr(item, 'variables') and item.variables:
        variables_list = [
            {"name": v.name, "options": [o.strip() for o in v.options.split(",") if o.strip()]}
            for v in sorted(item.variables, key=lambda v: v.position)
        ]

    # Build variants list from loaded relationships
    variants_list = None
    if hasattr(item, 'variants') and item.variants:
        variants_list = [
            VariantResponse(
                id=v.id,
                item_id=v.item_id,
                sku=v.sku,
                barcode=v.barcode,
                variable_1_value=v.variable_1_value,
                variable_2_value=v.variable_2_value,
                price=v.price,
                quantity=v.quantity,
                photo_url=v.photo_url,
                status=v.status,
                created_at=v.created_at,
            )
            for v in item.variants
            if v.status == "active"
        ]

    return ItemResponse(
        id=item.id,
        vendor_id=item.vendor_id,
        sku=item.sku,
        barcode=item.barcode,
        name=item.name,
        description=item.description,
        category=item.category,
        price=item.price,
        quantity=item.quantity,
        photo_urls=item.photo_urls,
        is_online=item.is_online,
        is_tax_exempt=item.is_tax_exempt,
        is_consignment=item.is_consignment,
        consignment_rate=item.consignment_rate,
        sale_price=item.sale_price,
        sale_start=item.sale_start,
        sale_end=item.sale_end,
        status=item.status,
        label_style=item.label_style or "standard",
        image_path=item.image_path,
        created_at=item.created_at,
        booth_number=booth_number,
        label_printed=item.label_printed,
        cost=getattr(item, 'cost', None),
        variables=variables_list,
        variants=variants_list,
    )


@router.get("/", response_model=List[ItemResponse])
async def list_items(
    status_filter: Optional[str] = Query(None, alias="status"),
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search by name or barcode"),
    vendor_id: Optional[int] = Query(None, description="Filter by vendor (admin/cashier only)"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    await _require_view_items(db, current_user)

    query = select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants))
    if current_user.role == "vendor":
        query = query.where(Item.vendor_id == current_user.id)
    elif vendor_id:
        query = query.where(Item.vendor_id == vendor_id)
    if status_filter:
        query = query.where(Item.status == status_filter)
    if category:
        query = query.where(Item.category == category)
    if q:
        term = f"%{q.lower()}%"
        query = query.where(
            or_(
                func.lower(Item.name).like(term),
                func.lower(Item.barcode).like(term),
                func.lower(Item.sku).like(term),
            )
        )
    query = query.order_by(Item.created_at.desc()).limit(limit)

    result = await db.execute(query)
    items = result.scalars().all()
    return [item_to_response(i) for i in items]


@router.get("/listing", response_model=ItemListingResponse)
async def list_items_listing(
    status_filter: Optional[str] = Query(None, alias="status"),
    q: Optional[str] = Query(None, description="Search by name, barcode, or sku"),
    vendor_id: Optional[int] = Query(None, description="Filter by vendor (admin/cashier only)"),
    limit: int = Query(25, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created_at"),
    sort_dir: str = Query("desc"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    await _require_view_items(db, current_user)

    allowed_sorts = {
        "created_at": Item.created_at,
        "name": Item.name,
        "price": Item.price,
        "quantity": Item.quantity,
        "status": Item.status,
    }
    if sort_by not in allowed_sorts:
        raise HTTPException(status_code=400, detail="Invalid sort column")
    if sort_dir not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="Invalid sort direction")

    base_filters = []
    if current_user.role == "vendor":
        base_filters.append(Item.vendor_id == current_user.id)
    elif vendor_id:
        base_filters.append(Item.vendor_id == vendor_id)

    if q:
        term = f"%{q}%"
        base_filters.append(
            or_(
                Item.name.ilike(term),
                Item.barcode.ilike(term),
                Item.sku.ilike(term),
            )
        )

    from app.models.sale import Sale
    sold_subq = (
        select(SaleItem.item_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(Sale.is_voided.is_(False))
        .group_by(SaleItem.item_id)
    )
    if current_user.role == "vendor":
        sold_subq = sold_subq.where(SaleItem.vendor_id == current_user.id)
    sold_subq = sold_subq.subquery()

    counts_query = select(
        func.count(Item.id).label("total"),
        func.count(Item.id).filter(Item.status == "active").label("active_count"),
        func.count(Item.id).filter(Item.status == "inactive").label("inactive_count"),
        func.count(Item.id).filter(Item.status.in_(("sold", "removed", "pending_delete"))).label("archive_count"),
        func.count(Item.id).filter(Item.id.in_(select(sold_subq.c.item_id))).label("sold_count"),
    )
    if base_filters:
        counts_query = counts_query.where(*base_filters)
    counts_result = await db.execute(counts_query)
    counts = counts_result.one()

    item_query = select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants))
    if base_filters:
        item_query = item_query.where(*base_filters)
    if status_filter == "active":
        item_query = item_query.where(Item.status == "active")
    elif status_filter == "inactive":
        item_query = item_query.where(Item.status == "inactive")
    elif status_filter == "archive":
        item_query = item_query.where(Item.status.in_(("sold", "removed", "pending_delete")))
    elif status_filter == "sold":
        item_query = item_query.where(Item.id.in_(select(sold_subq.c.item_id)))

    sort_column = allowed_sorts[sort_by]
    if sort_dir == "asc":
        item_query = item_query.order_by(sort_column.asc(), Item.id.asc())
    else:
        item_query = item_query.order_by(sort_column.desc(), Item.id.desc())

    item_query = item_query.offset(offset).limit(limit)
    result = await db.execute(item_query)
    items = result.scalars().all()

    if status_filter == "active":
        total = counts.active_count or 0
    elif status_filter == "inactive":
        total = counts.inactive_count or 0
    elif status_filter == "archive":
        total = counts.archive_count or 0
    elif status_filter == "sold":
        total = counts.sold_count or 0
    else:
        total = counts.total or 0

    return ItemListingResponse(
        items=[item_to_response(i) for i in items],
        total=int(total or 0),
        active_count=int(counts.active_count or 0),
        inactive_count=int(counts.inactive_count or 0),
        archive_count=int(counts.archive_count or 0),
        sold_count=int(counts.sold_count or 0),
    )


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    request: Request,
    data: ItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    await _require_manage_items(db, current_user)

    if current_user.role == "vendor":
        vendor_id = current_user.id
    else:
        if not data.vendor_id:
            raise HTTPException(status_code=400, detail="vendor_id is required for admin/cashier")
        vendor_id = data.vendor_id

    sku = await generate_sku(vendor_id, db)

    if data.barcode:
        barcode_val = data.barcode
        existing = await db.execute(select(Item).where(Item.barcode == barcode_val))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Barcode already exists")
    else:
        barcode_val = await generate_short_barcode(db)

    has_photos = bool(data.photo_urls and len(data.photo_urls) > 0)
    is_online_val = data.is_online if has_photos else False

    if is_online_val:
        require_result = await db.execute(
            select(StoreSetting.value).where(StoreSetting.key == "require_photo_description_online")
        )
        require_val = require_result.scalar_one_or_none()
        if require_val is None:
            require_val = "true"
        if require_val in ("true", "1"):
            if not has_photos:
                raise HTTPException(status_code=400, detail="Items must have at least one photo to be listed online")
            if not data.description or not data.description.strip():
                raise HTTPException(status_code=400, detail="Items must have a description to be listed online")

    item = Item(
        vendor_id=vendor_id,
        sku=sku,
        barcode=barcode_val,
        name=data.name,
        description=data.description,
        category=data.category,
        price=data.price,
        quantity=data.quantity,
        photo_urls=data.photo_urls,
        is_online=is_online_val,
        is_tax_exempt=data.is_tax_exempt,
        is_consignment=False,
        consignment_rate=None,
        sale_price=data.sale_price,
        sale_start=data.sale_start,
        sale_end=data.sale_end,
        label_style=data.label_style or "standard",
        cost=data.cost,
    )
    db.add(item)
    await db.flush()  # flush to get item.id

    # Save variables and variants if provided
    if data.variables or data.variants:
        await _save_variables_and_variants(db, item, data.variables, data.variants)

    await db.commit()

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item.id)
    )
    item = result.scalar_one()
    return item_to_response(item)


@router.get("/barcode/{barcode}", response_model=ItemResponse)
async def get_item_by_barcode(
    barcode: str,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(func.upper(Item.barcode) == barcode.upper())
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if current_user.role in ("admin", "cashier"):
        await _require_view_items(db, current_user)
    else:
        if item.vendor_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
        await _require_manage_items(db, current_user)
    return item_to_response(item)


@router.get("/{item_id}/dymo-label")
async def get_label_pdf(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if not await role_feature_allowed(db, current_user, "role_print_labels"):
        raise HTTPException(
            status_code=403,
            detail="Label printing is disabled for your role in Settings → User Roles.",
        )

    # Lazy barcode upgrade on single-label reprint.
    await maybe_upgrade_barcode(item, db)

    pdf_bytes = generate_label_pdf(item)

    item.label_printed = True
    await db.commit()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="label_{item_id}.pdf"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.post("/labels/batch-print")
async def get_batch_labels_pdf(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    """
    Batch label printing. Returns a multi-page PDF (one 1.5"W×1.0"H
    label per page) generated by the same precision-tuned thermal
    renderer used for single labels, so batch output is pixel-
    identical to the per-card single-label path and remains
    scannable on the Dymo LabelWriter 450.
    """
    entries = data.get("items", None)
    if entries:
        item_ids = [e["item_id"] for e in entries]
        qty_map = {e["item_id"]: max(1, min(99, int(e.get("quantity", 1)))) for e in entries}
    else:
        item_ids = data.get("item_ids", [])
        qty_map = {iid: 1 for iid in item_ids}

    if not item_ids or len(item_ids) > 200:
        raise HTTPException(status_code=400, detail="Provide 1-200 item IDs")

    total_labels = sum(qty_map.values())
    if total_labels > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 labels per batch")

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id.in_(item_ids))
    )
    items = result.scalars().all()
    if not items:
        raise HTTPException(status_code=404, detail="No items found")

    if current_user.role not in ("admin", "cashier"):
        for item in items:
            if item.vendor_id != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")

    if not await role_feature_allowed(db, current_user, "role_print_labels"):
        raise HTTPException(
            status_code=403,
            detail="Label printing is disabled for your role in Settings -> User Roles.",
        )

    id_order = {iid: idx for idx, iid in enumerate(item_ids)}
    items_sorted = sorted(items, key=lambda it: id_order.get(it.id, 0))

    # Lazy barcode upgrade: on reprint, convert any non-scanable codes to
    # fresh 6-digit numeric codes so the new label prints with Subset C.
    # Skip MAN-* manual items and codes that are already 6 digits.
    for item in items_sorted:
        await maybe_upgrade_barcode(item, db)

    expanded = []
    for item in items_sorted:
        count = qty_map.get(item.id, 1)
        for _ in range(count):
            expanded.append(item)

    pdf_bytes = generate_label_pdf_batch(expanded)

    for item in items:
        item.label_printed = True
    await db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'inline; filename="labels.pdf"',
        },
    )


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _require_view_items(db, current_user)

    return item_to_response(item)


@router.put("/{item_id}", response_model=ItemResponse)
async def update_item(
    request: Request,
    item_id: int,
    data: ItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _require_manage_items(db, current_user)

    update_data = data.model_dump(exclude_none=True)
    if update_data.get("is_online"):
        current_photos = update_data.get("photo_urls", item.photo_urls) or []
        has_image = bool(item.image_path) if hasattr(item, 'image_path') else False
        new_desc = update_data.get("description", item.description)

        require_result = await db.execute(
            select(StoreSetting.value).where(StoreSetting.key == "require_photo_description_online")
        )
        require_val = require_result.scalar_one_or_none()
        if require_val is None:
            require_val = "true"
        if require_val in ("true", "1"):
            if not current_photos and not has_image:
                raise HTTPException(status_code=400, detail="Items must have at least one photo to be listed online")
            if not new_desc or not new_desc.strip():
                raise HTTPException(status_code=400, detail="Items must have a description to be listed online")
        else:
            if not current_photos and not has_image:
                raise HTTPException(status_code=400, detail="Items must have a photo to be listed online")
    update_data.pop("is_consignment", None)
    update_data.pop("consignment_rate", None)

    # Extract variables/variants before setting fields
    variables_data = update_data.pop("variables", None)
    variants_data = update_data.pop("variants", None)

    for field, value in update_data.items():
        setattr(item, field, value)

    if item.status == "sold" and (item.quantity or 0) > 0:
        item.status = "active"

    # Save variables and variants if provided
    if variables_data is not None or variants_data is not None:
        await _save_variables_and_variants(
            db, item,
            variables_data=variables_data,
            variants_data=variants_data,
        )

    await db.commit()

    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="update_item",
        entity_type="item",
        entity_id=str(item_id),
        request=request,
    )

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item.id)
    )
    item = result.scalar_one()
    return item_to_response(item)


@router.post("/{item_id}/photo", response_model=ItemResponse)
async def upload_item_photo(
    request: Request,
    item_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _require_manage_items(db, current_user)

    allowed = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    ext = os.path.splitext(file.filename or "photo.jpg")[1].lower() or ".jpg"
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    # Validate actual file content matches declared image type
    declared_type = file.content_type or "application/octet-stream"
    from app.services.upload_security import _validate_image_content
    try:
        _validate_image_content(contents, declared_type)
    except HTTPException:
        # Fallback: try detecting from file extension if content_type is missing/wrong
        ext_to_mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}
        detected_mime = ext_to_mime.get(ext)
        if detected_mime:
            _validate_image_content(contents, detected_mime)
        else:
            raise

    filename = f"{item_id}_{uuid.uuid4().hex[:10]}.jpg"

    try:
        img = Image.open(io.BytesIO(contents))
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            ratio = MAX_IMAGE_DIMENSION / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        jpeg_bytes = buf.getvalue()
    except Exception:
        jpeg_bytes = contents

    spaces_key = f"items/{filename}"
    cdn_url = spaces_svc.upload_bytes(jpeg_bytes, spaces_key, "image/jpeg")
    if cdn_url:
        photo_url = cdn_url
    else:
        from app.services.upload_security import save_upload
        filepath = save_upload(PHOTO_UPLOAD_DIR, filename, jpeg_bytes)
        photo_url = f"/static/images/items/{filename}"

    # Track image metadata in DB (binary data stored on disk/DO Spaces only)
    existing = await db.execute(
        select(ItemImage).where(ItemImage.item_id == item_id)
    )
    old_img = existing.scalar_one_or_none()
    if old_img:
        old_img.content_type = "image/jpeg"
    else:
        db.add(ItemImage(item_id=item_id, content_type="image/jpeg", image_data=b""))

    existing_urls = item.photo_urls or []
    if len(existing_urls) >= MAX_ITEM_PHOTOS:
        raise HTTPException(
            status_code=400,
            detail=f"Items can have up to {MAX_ITEM_PHOTOS} photos.",
        )

    item.photo_urls = existing_urls + [photo_url]
    item.image_path = photo_url
    await db.commit()

    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="upload_item_photo",
        entity_type="item",
        entity_id=str(item_id),
        request=request,
    )

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item.id)
    )
    item = result.scalar_one()
    return item_to_response(item)


@router.delete("/{item_id}/photo", response_model=ItemResponse)
async def delete_item_photo(
    item_id: int,
    photo_url: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _require_manage_items(db, current_user)

    urls = [u for u in (item.photo_urls or []) if u != photo_url]
    item.photo_urls = urls if urls else None

    if photo_url.startswith("http"):
        spaces_svc.delete_object(photo_url)
    else:
        filename = os.path.basename(photo_url)
        filepath = os.path.join(PHOTO_UPLOAD_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)

    if item.image_path == photo_url:
        item.image_path = urls[0] if urls else None
    await db.commit()

    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="create_item",
        entity_type="item",
        entity_id=str(item.id),
        details=f"SKU: {item.sku}, Name: {item.name}",
        request=request,
    )

    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item.id)
    )
    item = result.scalar_one()
    return item_to_response(item)


@router.post("/{item_id}/upload-image")
async def upload_item_image(
    item_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(
        select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _require_manage_items(db, current_user)

    ext = os.path.splitext(file.filename or "photo.jpg")[1].lower()
    if ext not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only jpg, jpeg, png, webp files are allowed")

    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    # Validate actual file content matches declared image type
    declared_type = file.content_type or "application/octet-stream"
    from app.services.upload_security import _validate_image_content
    try:
        _validate_image_content(contents, declared_type)
    except HTTPException:
        ext_to_mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        detected_mime = ext_to_mime.get(ext)
        if detected_mime:
            _validate_image_content(contents, detected_mime)
        else:
            raise

    img = Image.open(io.BytesIO(contents))
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_IMAGE_DIMENSION:
        ratio = MAX_IMAGE_DIMENSION / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    jpeg_bytes = buf.getvalue()

    filename = f"{item_id}.jpg"
    spaces_key = f"items/{filename}"
    cdn_url = spaces_svc.upload_bytes(jpeg_bytes, spaces_key, "image/jpeg")
    if cdn_url:
        image_path = cdn_url
    else:
        from app.services.upload_security import save_upload
        save_upload(IMAGE_UPLOAD_DIR, filename, jpeg_bytes)
        image_path = f"/static/uploads/items/{filename}"

    # Track image metadata in DB (binary data stored on disk/DO Spaces only)
    existing = await db.execute(
        select(ItemImage).where(ItemImage.item_id == item_id)
    )
    old_img = existing.scalar_one_or_none()
    if old_img:
        old_img.content_type = "image/jpeg"
    else:
        db.add(ItemImage(item_id=item_id, content_type="image/jpeg", image_data=b""))

    item.image_path = image_path
    await db.commit()

    return {"success": True, "image_path": image_path}


@router.get("/{item_id}/image")
async def get_item_image(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Serve item image from disk. Images are stored on disk/DO Spaces, not in DB."""
    # Check item for photo_url first
    result = await db.execute(
        select(Item).where(Item.id == item_id)
    )
    item = result.scalar_one_or_none()
    if item and item.image_path:
        # If it's a full URL (CDN), redirect to it
        if item.image_path.startswith("http"):
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=item.image_path)
        # Otherwise serve from disk
        filepath = os.path.join("frontend", item.image_path.lstrip("/"))
        if os.path.exists(filepath):
            with open(filepath, "rb") as f:
                data = f.read()
            return Response(content=data, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})

    # Fallback to legacy paths
    for path in [
        os.path.join(IMAGE_UPLOAD_DIR, f"{item_id}.jpg"),
        os.path.join(PHOTO_UPLOAD_DIR, f"{item_id}.jpg"),
    ]:
        if os.path.exists(path):
            with open(path, "rb") as f:
                data = f.read()
            return Response(content=data, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})

    raise HTTPException(status_code=404, detail="Image not found")


@router.post("/bulk-status")
async def bulk_set_item_status(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    vendor_id = body.get("vendor_id")
    target_status = body.get("status", "active")

    if target_status not in ("active", "inactive"):
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'inactive'")

    if current_user.role == "vendor":
        vendor_id = current_user.id
    elif not vendor_id:
        raise HTTPException(status_code=400, detail="vendor_id is required for admin/cashier")

    if current_user.role not in ("admin", "cashier") and vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _require_manage_items(db, current_user)

    opposite = "inactive" if target_status == "active" else "active"
    result = await db.execute(
        select(Item).where(Item.vendor_id == vendor_id, Item.status == opposite)
    )
    items = result.scalars().all()
    updated = 0
    for item in items:
        item.status = target_status
        if target_status == "inactive":
            item.is_online = False
        updated += 1

    await db.commit()
    label = "for sale" if target_status == "active" else "not for sale"
    return {"detail": f"{updated} item(s) marked {label}.", "updated": updated}


@router.post("/bulk-sale")
async def bulk_apply_sale(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    """Apply a percentage-off sale to multiple items at once."""
    await _require_manage_items(db, current_user)

    item_ids = body.get("item_ids", [])
    percent_off = body.get("percent_off")
    sale_start = body.get("sale_start")
    sale_end = body.get("sale_end")

    if not item_ids:
        raise HTTPException(status_code=400, detail="No items selected")
    if not percent_off or float(percent_off) <= 0 or float(percent_off) > 100:
        raise HTTPException(status_code=400, detail="Percent off must be between 1 and 100")
    if not sale_start or not sale_end:
        raise HTTPException(status_code=400, detail="Sale start and end dates are required")
    sale_start = _parse_iso_date(sale_start, "sale_start")
    sale_end = _parse_iso_date(sale_end, "sale_end")
    if sale_end < sale_start:
        raise HTTPException(status_code=400, detail="Sale end must be after sale start")

    percent = Decimal(str(percent_off)) / Decimal("100")

    query = select(Item).where(Item.id.in_(item_ids))
    if current_user.role == "vendor":
        query = query.where(Item.vendor_id == current_user.id)

    result = await db.execute(query)
    items = result.scalars().all()

    updated = 0
    for item in items:
        original_price = Decimal(str(item.price))
        sale_price = (original_price * (Decimal("1") - percent)).quantize(Decimal("0.01"))
        item.sale_price = sale_price
        item.sale_start = sale_start
        item.sale_end = sale_end
        updated += 1

    await db.commit()
    return {"updated": updated, "percent_off": float(percent_off), "sale_start": sale_start, "sale_end": sale_end}


@router.post("/bulk-clear-sale")
async def bulk_clear_sale(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    """Remove sale pricing from multiple items at once."""
    await _require_manage_items(db, current_user)

    item_ids = body.get("item_ids", [])
    if not item_ids:
        raise HTTPException(status_code=400, detail="No items selected")

    query = select(Item).where(Item.id.in_(item_ids))
    if current_user.role == "vendor":
        query = query.where(Item.vendor_id == current_user.id)

    result = await db.execute(query)
    items = result.scalars().all()

    updated = 0
    for item in items:
        item.sale_price = None
        item.sale_start = None
        item.sale_end = None
        updated += 1

    await db.commit()
    return {"cleared": updated}


@router.patch("/{item_id}/toggle-status", response_model=ItemResponse)
async def toggle_item_status(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _require_manage_items(db, current_user)

    if item.status not in ("active", "inactive"):
        raise HTTPException(status_code=409, detail=f"Cannot toggle status of {item.status} items")
    item.status = "inactive" if item.status == "active" else "active"
    await db.commit()
    await db.refresh(item)
    return item_to_response(item)


@router.patch("/{item_id}/reactivate", response_model=ItemResponse)
async def reactivate_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(select(Item).options(selectinload(Item.vendor), selectinload(Item.variables), selectinload(Item.variants)).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if not await _can_reactivate_archived_items(db, current_user):
        raise HTTPException(
            status_code=403,
            detail="Archived item reactivation is not enabled for your role.",
        )

    if item.status != "pending_delete":
        raise HTTPException(status_code=409, detail=f"Cannot reactivate {item.status} items")

    item.status = "active"
    item.archive_expires_at = None
    await db.commit()
    await db.refresh(item)
    return item_to_response(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    request: Request,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    result = await db.execute(select(Item).where(Item.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if current_user.role not in ("admin", "cashier") and item.vendor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    await _require_manage_items(db, current_user)

    item.status = "removed"
    await db.commit()

    await log_audit(
        db=db,
        vendor_id=current_user.id,
        action="delete_item",
        entity_type="item",
        entity_id=str(item_id),
        request=request,
    )
