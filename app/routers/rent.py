import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance
from app.models.rent import RentPayment
from app.models.legacy_history import LegacyFinancialHistory
from app.models.sale import Sale, SaleItem
from app.models.item import Item
from app.routers.auth import get_current_user
from app.routers.settings import role_feature_allowed
from app.services.rent_payments import apply_rent_payment, display_rent_notes, extract_rent_reference, stamp_rent_notes
from app.timezone import STORE_TZ

router = APIRouter(prefix="/vendor", tags=["vendor-rent"])


def _serialize_legacy_entry(entry: LegacyFinancialHistory) -> dict:
    return {
        "id": entry.id,
        "entry_type": entry.entry_type,
        "source_system": entry.source_system,
        "reference_kind": entry.reference_kind,
        "amount": float(entry.amount or 0),
        "entry_date": entry.entry_date.isoformat() if entry.entry_date else None,
        "period_month": entry.period_month.isoformat() if entry.period_month else None,
        "description": entry.description,
        "source_name": entry.source_name,
        "source_email": entry.source_email,
        "source_reference": entry.source_reference,
        "import_batch": entry.import_batch,
        "imported_at": entry.imported_at.isoformat() if entry.imported_at else None,
    }


def _has_vendor_booth_access(user: Vendor) -> bool:
    return user.role == "vendor" or bool(getattr(user, "is_vendor", False))


def _month_window(month: str | None):
    if month:
        try:
            year, mon = month.split("-")
            start_local = datetime(int(year), int(mon), 1, tzinfo=STORE_TZ)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid month. Use YYYY-MM.")
    else:
        today = datetime.now(STORE_TZ)
        start_local = datetime(today.year, today.month, 1, tzinfo=STORE_TZ)
    if start_local.month == 12:
        end_local = datetime(start_local.year + 1, 1, 1, tzinfo=STORE_TZ)
    else:
        end_local = datetime(start_local.year, start_local.month + 1, 1, tzinfo=STORE_TZ)
    return start_local, end_local, start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _visible_rent_history_rows(payments: list[RentPayment]) -> list[RentPayment]:
    receipt_refs = {
        extract_rent_reference(p.notes)
        for p in payments
        if p.status == "received" and extract_rent_reference(p.notes)
    }
    visible: list[RentPayment] = []
    for p in payments:
        ref = extract_rent_reference(p.notes)
        if p.status == "paid" and ref and ref in receipt_refs:
            continue
        visible.append(p)
    return visible


@router.get("/rent-status")
async def rent_status(
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if not _has_vendor_booth_access(current_vendor):
        raise HTTPException(status_code=403, detail="Vendor access required.")

    vendor = current_vendor
    today = date.today()
    period = date(today.year, today.month, 1)

    existing = await db.execute(
        select(RentPayment).where(
            RentPayment.vendor_id == vendor.id,
            RentPayment.period_month == period,
        )
    )
    current_payment = existing.scalar_one_or_none()

    history_result = await db.execute(
        select(RentPayment)
        .where(RentPayment.vendor_id == vendor.id)
        .order_by(RentPayment.period_month.desc())
        .limit(12)
    )
    history = _visible_rent_history_rows(history_result.scalars().all())

    legacy_result = await db.execute(
        select(LegacyFinancialHistory)
        .where(
            LegacyFinancialHistory.vendor_id == vendor.id,
            LegacyFinancialHistory.entry_type == "rent",
        )
        .order_by(
            LegacyFinancialHistory.entry_date.desc().nullslast(),
            LegacyFinancialHistory.imported_at.desc(),
        )
        .limit(24)
    )
    legacy_history = legacy_result.scalars().all()

    balance_result = await db.execute(
        select(VendorBalance).where(VendorBalance.vendor_id == vendor.id)
    )
    balance = balance_result.scalar_one_or_none()
    rent_credit = float(balance.rent_balance or 0) if balance and balance.rent_balance is not None else 0.0

    landing_fee = float(vendor.landing_page_fee or 0)
    effective_rent = float(vendor.monthly_rent or 0) + landing_fee

    return {
        "monthly_rent": float(vendor.monthly_rent or 0),
        "landing_page_fee": landing_fee,
        "effective_rent": effective_rent,
        "current_month": today.strftime("%B %Y"),
        "paid_this_month": current_payment is not None and current_payment.status == "paid",
        "pending_this_month": current_payment is not None and current_payment.status == "pending",
        "rent_credit": rent_credit,
        "history": [
            {
                "period": p.period_month.strftime("%B %Y"),
                "amount": float(p.amount),
                "method": p.method,
                "status": p.status,
                "date": p.processed_at.strftime("%m/%d/%Y") if p.processed_at else None,
                "notes": display_rent_notes(p.notes),
            }
            for p in history
        ],
        "legacy_history": [_serialize_legacy_entry(entry) for entry in legacy_history],
    }


class RentConfirmRequest(BaseModel):
    square_payment_id: Optional[str] = None
    amount: Optional[Decimal] = None
    period: Optional[str] = None


class VendorRentRequest(BaseModel):
    amount: Optional[Decimal] = None
    period: Optional[str] = None


@router.get("/monthly-report")
async def monthly_report(
    month: Optional[str] = None,
    vendor_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    is_staff = current_vendor.role in ("admin", "cashier")
    if is_staff:
        allowed = (
            current_vendor.role == "admin"
            or await role_feature_allowed(db, current_vendor, "role_manage_vendors")
            or await role_feature_allowed(db, current_vendor, "role_manage_rent")
            or await role_feature_allowed(db, current_vendor, "role_view_reports")
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="Staff access required.")
        target_vendor_id = vendor_id or current_vendor.id
        result = await db.execute(select(Vendor).where(Vendor.id == target_vendor_id))
        vendor = result.scalar_one_or_none()
        if not vendor or vendor.role != "vendor":
            raise HTTPException(status_code=404, detail="Vendor not found.")
    else:
        if not _has_vendor_booth_access(current_vendor):
            raise HTTPException(status_code=403, detail="Vendor access required.")
        vendor = current_vendor

    start_local, end_local, start_utc, end_utc = _month_window(month)

    balance_result = await db.execute(
        select(VendorBalance).where(VendorBalance.vendor_id == vendor.id)
    )
    balance = balance_result.scalar_one_or_none()
    total_sales = float(balance.balance or 0) if balance and balance.balance is not None else 0.0
    carry_over = float(balance.rent_balance or 0) if balance and balance.rent_balance is not None else 0.0
    rent_due_amt = float(vendor.monthly_rent or 0) + float(vendor.landing_page_fee or 0)

    # Check if rent already paid this month
    today_check = date.today()
    current_period_check = date(today_check.year, today_check.month, 1)
    rp_check = await db.execute(
        select(RentPayment).where(
            RentPayment.vendor_id == vendor.id,
            RentPayment.period_month == current_period_check,
            RentPayment.status == "paid",
        )
    )
    rent_paid_this_month = rp_check.scalar_one_or_none() is not None

    if rent_due_amt > 0 and not rent_paid_this_month:
        net_payout = round(total_sales - rent_due_amt + carry_over, 2)
    else:
        net_payout = round(total_sales + carry_over, 2)

    sales_summary = await db.execute(
        select(
            func.coalesce(func.sum(SaleItem.line_total), 0).label("gross_sales"),
            func.coalesce(func.sum(SaleItem.quantity), 0).label("items_sold"),
            func.count(func.distinct(Sale.id)).label("transactions"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            SaleItem.vendor_id == vendor.id,
            Sale.is_voided.is_(False),
            Sale.created_at >= start_utc,
            Sale.created_at < end_utc,
        )
    )
    summary_row = sales_summary.one()

    sold_items_result = await db.execute(
        select(
            SaleItem.item_id.label("item_id"),
            Item.name.label("item_name"),
            Item.sku.label("sku"),
            func.coalesce(func.sum(SaleItem.quantity), 0).label("qty_sold"),
            func.coalesce(func.sum(SaleItem.line_total), 0).label("gross_sales"),
            func.max(Sale.created_at).label("last_sold_at"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Item, Item.id == SaleItem.item_id)
        .where(
            SaleItem.vendor_id == vendor.id,
            Sale.is_voided.is_(False),
            Sale.created_at >= start_utc,
            Sale.created_at < end_utc,
        )
        .group_by(SaleItem.item_id, Item.name, Item.sku)
        .order_by(func.sum(SaleItem.line_total).desc(), func.max(Sale.created_at).desc())
    )
    sold_items = sold_items_result.all()

    rent_result = await db.execute(
        select(RentPayment)
        .where(
            RentPayment.vendor_id == vendor.id,
            RentPayment.processed_at >= start_utc,
            RentPayment.processed_at < end_utc,
        )
        .order_by(RentPayment.processed_at.desc())
    )
    rent_payments = _visible_rent_history_rows(rent_result.scalars().all())

    return {
        "vendor": {
            "id": vendor.id,
            "name": vendor.name,
            "email": vendor.email,
            "booth_number": vendor.booth_number or "—",
            "monthly_rent": float(vendor.monthly_rent or 0),
            "landing_page_fee": float(vendor.landing_page_fee or 0),
            "effective_rent": float(vendor.monthly_rent or 0) + float(vendor.landing_page_fee or 0),
            "payout_method": vendor.payout_method or "check",
        },
        "month": start_local.strftime("%Y-%m"),
        "month_label": start_local.strftime("%B %Y"),
        "period_start": start_local.date().isoformat(),
        "period_end": (end_local.date() - timedelta(days=1)).isoformat(),
        "summary": {
            "gross_sales": round(float(summary_row.gross_sales or 0), 2),
            "items_sold": int(summary_row.items_sold or 0),
            "transactions": int(summary_row.transactions or 0),
            "total_sales": round(total_sales, 2),
            "rent_due": round(rent_due_amt, 2),
            "net_payout": net_payout,
            "carry_over": round(carry_over, 2),
            "rent_paid_this_month": rent_paid_this_month,
        },
        "sold_items": [
            {
                "item_id": row.item_id,
                "item_name": row.item_name,
                "sku": row.sku,
                "qty_sold": int(row.qty_sold or 0),
                "gross_sales": round(float(row.gross_sales or 0), 2),
                "last_sold_at": row.last_sold_at.isoformat() if row.last_sold_at else None,
            }
            for row in sold_items
        ],
        "rent_payments": [
            {
                "id": p.id,
                "amount": float(p.amount or 0),
                "method": p.method,
                "status": p.status,
                "notes": display_rent_notes(p.notes),
                "period_month": p.period_month.strftime("%B %Y") if p.period_month else None,
                "processed_at": p.processed_at.isoformat() if p.processed_at else None,
            }
            for p in rent_payments
        ],
    }


@router.post("/pay-rent")
async def pay_rent(
    body: VendorRentRequest,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if not _has_vendor_booth_access(current_vendor):
        raise HTTPException(status_code=403, detail="Vendor access required.")

    vendor = current_vendor
    configured_rent = Decimal(str(vendor.monthly_rent or 0)) + Decimal(str(vendor.landing_page_fee or 0))
    if configured_rent <= 0:
        raise HTTPException(status_code=400, detail="No rent amount configured for this vendor.")

    try:
        amount = Decimal(str(body.amount if body.amount is not None else configured_rent))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount.")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount.")

    if body.period:
        try:
            parts = body.period.split("-")
            period = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid period. Use YYYY-MM.")
    else:
        today = date.today()
        period = date(today.year, today.month, 1)

    price_cents = round(float(amount) * 100)
    month_label = period.strftime("%B %Y")
    redirect_url = (
        f"https://www.bowenstreetmm.com/vendor/dashboard.html"
        f"?rent_paid=success&vendor_id={vendor.id}"
        f"&rent_amount={float(amount):.2f}&rent_period={period.isoformat()}"
    )

    try:
        from app.services.square import create_payment_link
        result = await create_payment_link(
            name=f"Rent payment - {vendor.name} - {month_label}",
            price_cents=price_cents,
            redirect_url=redirect_url,
        )
        return {"payment_url": result["url"]}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Rent payment could not be initiated. Please try again or contact the office.",
        )


@router.post("/rent-confirmed")
async def rent_confirmed(
    body: RentConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_vendor: Vendor = Depends(get_current_user),
):
    if not _has_vendor_booth_access(current_vendor):
        raise HTTPException(status_code=403, detail="Vendor access required.")

    vendor = current_vendor
    try:
        amount = Decimal(str(body.amount if body.amount is not None else vendor.monthly_rent)) + Decimal(str(vendor.landing_page_fee or 0))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount.")

    if body.period:
        try:
            parts = body.period.split("-")
            period = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid period. Use YYYY-MM.")
    else:
        today = date.today()
        period = date(today.year, today.month, 1)

    reference_tag = secrets.token_hex(4)
    base_notes = body.square_payment_id or "Square online payment"
    allocation = await apply_rent_payment(
        db=db,
        vendor=vendor,
        amount=amount,
        requested_period=period,
        method="square",
        notes=base_notes,
        reference_tag=reference_tag,
    )
    applied_periods = allocation["applied_periods"]
    credit_remainder = allocation["credit_remainder"]
    period_labels = ", ".join(p.strftime('%B %Y') for p in applied_periods)
    receipt_notes = base_notes
    if applied_periods:
        receipt_notes = f"{receipt_notes} Applied to {period_labels}."
    if credit_remainder > 0:
        receipt_notes = f"{receipt_notes} Remaining rent credit ${float(credit_remainder):.2f}."
    db.add(RentPayment(
        vendor_id=vendor.id,
        amount=amount,
        period_month=period,
        method="square",
        status="received",
        notes=stamp_rent_notes(receipt_notes, reference_tag),
    ))
    await db.commit()
    if applied_periods and credit_remainder > 0:
        message = (
            f"Rent payment recorded. Applied to {', '.join(p.strftime('%B %Y') for p in applied_periods)}. "
            f"Remaining credit ${float(credit_remainder):.2f} stays on your rent account."
        )
    elif applied_periods:
        message = (
            f"Rent payment recorded for {', '.join(p.strftime('%B %Y') for p in applied_periods)}."
        )
    else:
        message = (
            f"Rent payment recorded. The full amount remains as rent credit until a full month is covered."
        )

    return {
        "success": True,
        "message": message,
        "applied_periods": [p.isoformat() for p in applied_periods],
        "credit_remainder": float(credit_remainder),
    }
