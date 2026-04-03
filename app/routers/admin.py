import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, text, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.vendor import Vendor, VendorBalance, BalanceAdjustment
from app.models.item import Item
from app.models.sale import Sale, SaleItem
from app.models.rent import RentPayment
from app.models.payout import Payout
from app.models.legacy_history import LegacyFinancialHistory
from app.models.gift_card import GiftCard, GiftCardTransaction
from app.models.reservation import Reservation
from app.models.studio_class import StudioClass
from app.models.studio_image import StudioImage
from app.models.class_registration import ClassRegistration
from app.models.item_image import ItemImage
from app.models.booth_showcase import BoothShowcase
from app.routers.auth import get_current_user, require_admin, require_cashier_or_admin
from app.services.email import send_email_safe
from app.services.rent_payments import apply_rent_payment
from app.services.email_templates import (
    payout_with_rent_email,
    rent_shortfall_email,
    rent_overdue_15day_email,
    rent_overdue_27day_email,
)
from app.routers.notifications import notify_weekly_report
from app.routers.settings import (
    get_setting,
    role_feature_allowed,
    require_any_staff_feature,
    require_staff_feature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _serialize_legacy_entry(entry: LegacyFinancialHistory) -> dict:
    return {
        "id": entry.id,
        "vendor_id": entry.vendor_id,
        "vendor_name": entry.vendor.name if getattr(entry, "vendor", None) else None,
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


async def require_vendor_hub_access(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
) -> Vendor:
    if current_user.role == "admin":
        return current_user
    if current_user.role == "cashier":
        for slug in (
            "role_view_dashboard",
            "role_manage_vendors",
            "role_manage_rent",
            "role_view_reports",
        ):
            if await role_feature_allowed(db, current_user, slug):
                return current_user
    raise HTTPException(
        status_code=403,
        detail="Vendor hub requires a staff dashboard permission in Settings → User Roles.",
    )


def _admin_display_rent_balance(
    rent_ledger: float,
    monthly_rent: float,
    current_month_rent_paid: bool,
) -> float:
    """
    Admin UI rent column: ledger prepaid/owed plus, when this month's rent is not yet paid,
    net the monthly obligation so vendors show negative rent (e.g. 0 - 227 = -227) instead of $0.
    """
    if monthly_rent > 0 and not current_month_rent_paid:
        return round(rent_ledger - monthly_rent, 2)
    return round(rent_ledger, 2)


def _admin_next_rent_projection(
    sales_balance: float,
    monthly_rent: float,
) -> float:
    """
    Admin UI headline balance: what the vendor would have left after the next rent charge.
    This is intentionally separate from the prepaid-rent ledger so the top-line number
    reflects current sales minus the next rent obligation.
    """
    if monthly_rent <= 0:
        return round(sales_balance, 2)
    return round(sales_balance - monthly_rent, 2)


def _rent_status(today: date, last_payment: Optional[RentPayment]) -> str:
    if last_payment is None:
        return "overdue"
    period = last_payment.period_month
    current_period = date(today.year, today.month, 1)
    if period >= current_period:
        return "current"
    days_since = (today - period).days
    if days_since >= 30:
        return "overdue"
    return "due"


@router.get("/vendor-overview")
async def vendor_overview(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_vendor_hub_access),
):
    """All vendor data for consolidated admin dashboard (balances, rent, payout preview)."""
    today = date.today()
    current_period = date(today.year, today.month, 1)
    period_label = current_period.strftime("%B %Y")

    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active", Vendor.role == "vendor").order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    bal_result = await db.execute(select(VendorBalance.vendor_id, VendorBalance.balance, VendorBalance.rent_balance))
    balance_map = {}
    rent_balance_map = {}
    for row in bal_result.all():
        balance_map[row.vendor_id] = float(row.balance) if row.balance is not None else 0.0
        rent_balance_map[row.vendor_id] = float(row.rent_balance) if row.rent_balance is not None else 0.0

    rent_result = await db.execute(
        select(RentPayment).where(RentPayment.period_month == current_period)
    )
    rent_map: dict = {}
    for rp in rent_result.scalars().all():
        rent_map[rp.vendor_id] = {
            "paid": rp.status == "paid",
            "method": rp.method,
            "amount": float(rp.amount),
            "date": rp.processed_at.strftime("%m/%d/%Y") if rp.processed_at else None,
        }

    last_rent_result = await db.execute(
        select(
            RentPayment.vendor_id,
            func.max(RentPayment.processed_at).label("last_date"),
        )
        .where(RentPayment.status == "paid")
        .group_by(RentPayment.vendor_id)
    )
    last_rent_map = {row.vendor_id: row.last_date for row in last_rent_result.all()}

    payout_result = await db.execute(
        select(Payout).where(Payout.period_month == current_period)
    )
    payout_map: dict = {}
    for p in payout_result.scalars().all():
        payout_map[p.vendor_id] = {
            "gross_sales": float(p.gross_sales),
            "rent_deducted": float(p.rent_deducted),
            "net_payout": float(p.net_payout),
            "status": p.status,
        }

    existing_any = await db.execute(
        select(Payout).where(Payout.period_month == current_period).limit(1)
    )
    already_processed = existing_any.scalar_one_or_none() is not None

    rows = []
    totals = {"gross": 0.0, "rent_due": 0.0, "rent_collected": 0.0, "net": 0.0, "shortfalls": 0.0}

    for v in vendors:
        sales_balance = balance_map.get(v.id, 0.0)
        rent_bal = rent_balance_map.get(v.id, 0.0)
        rent = float(v.monthly_rent or 0)
        rent_info = rent_map.get(v.id)
        rent_paid = rent_info is not None and rent_info["paid"]
        rent_display = _admin_display_rent_balance(rent_bal, rent, rent_paid)
        combined_balance = _admin_next_rent_projection(sales_balance, rent)
        last_rent_date = last_rent_map.get(v.id)
        payout_info = payout_map.get(v.id)

        if rent <= 0:
            rent_status = "none"
        elif rent_paid:
            rent_status = "current"
        else:
            if today.day > 15:
                rent_status = "overdue"
            else:
                rent_status = "due"

        rent_to_deduct = 0.0 if rent_paid else rent
        if sales_balance >= rent_to_deduct:
            net_payout = round(sales_balance - rent_to_deduct, 2)
            shortfall = 0.0
        else:
            net_payout = 0.0
            shortfall = round(rent_to_deduct - sales_balance, 2)

        totals["gross"] += sales_balance
        totals["rent_due"] += rent if not rent_paid else 0.0
        totals["rent_collected"] += rent_info["amount"] if rent_info and rent_paid else 0.0
        totals["net"] += net_payout
        totals["shortfalls"] += shortfall

        rows.append({
            "id": v.id,
            "name": v.name,
            "email": v.email or "",
            "phone": v.phone or "",
            "booth_number": v.booth_number or "—",
            "monthly_rent": rent,
            "balance": combined_balance,
            "sales_balance": round(sales_balance, 2),
            "rent_balance": rent_display,
            "rent_balance_ledger": round(rent_bal, 2),
            "combined_balance": combined_balance,
            "rent_status": rent_status,
            "rent_paid": rent_paid,
            "rent_paid_method": rent_info["method"] if rent_info else None,
            "rent_paid_date": rent_info["date"] if rent_info else None,
            "rent_flagged": v.rent_flagged,
            "last_rent_date": last_rent_date.strftime("%m/%d/%Y") if last_rent_date else None,
            "payout_preview": {
                "gross": round(sales_balance, 2),
                "rent_deducted": round(rent_to_deduct, 2),
                "net": net_payout,
                "shortfall": shortfall,
            },
            "payout_processed": payout_info is not None,
            "payout_method": v.payout_method or "—",
            "commission_rate": float(v.commission_rate or 0),
            "role": v.role,
            "status": v.status,
            "notes": v.notes or "",
        })

    return {
        "period": period_label,
        "already_processed": already_processed,
        "totals": {
            "gross_sales": round(totals["gross"], 2),
            "rent_due": round(totals["rent_due"], 2),
            "rent_collected": round(totals["rent_collected"], 2),
            "net_payouts": round(totals["net"], 2),
            "shortfalls": round(totals["shortfalls"], 2),
            "vendor_count": len(rows),
        },
        "vendors": rows,
    }


@router.get("/rent-status")
async def rent_status(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_any_staff_feature("role_manage_rent", "role_view_reports")),
):
    vendors_result = await db.execute(
        select(Vendor).where(
            Vendor.status == "active",
            Vendor.role == "vendor",
            Vendor.monthly_rent > 0,
        ).order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    today = date.today()
    vendor_ids = [v.id for v in vendors]

    payments_result = await db.execute(
        select(RentPayment)
        .where(RentPayment.vendor_id.in_(vendor_ids))
        .order_by(RentPayment.vendor_id, RentPayment.period_month.desc())
    )
    all_payments = payments_result.scalars().all()

    latest_by_vendor: dict[int, RentPayment] = {}
    for p in all_payments:
        if p.vendor_id not in latest_by_vendor:
            latest_by_vendor[p.vendor_id] = p

    rows = []
    total_collected_this_month = 0.0
    current_period = date(today.year, today.month, 1)

    for v in vendors:
        last = latest_by_vendor.get(v.id)
        status = _rent_status(today, last)
        if last and last.period_month >= current_period:
            total_collected_this_month += float(last.amount or 0)
        rows.append({
            "id": v.id,
            "name": v.name,
            "booth_number": v.booth_number or "—",
            "monthly_rent": float(v.monthly_rent or 0),
            "last_payment_date": last.processed_at.date().isoformat() if last else None,
            "last_payment_amount": float(last.amount) if last else None,
            "status": status,
            "rent_flagged": v.rent_flagged,
        })

    return {
        "vendors": rows,
        "total_collected_this_month": round(total_collected_this_month, 2),
        "month_label": today.strftime("%B %Y"),
    }


@router.post("/vendors/{vendor_id}/flag")
async def toggle_vendor_flag(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_any_staff_feature("role_manage_rent", "role_manage_vendors")),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    vendor.rent_flagged = not vendor.rent_flagged
    await db.commit()

    return {
        "id": vendor.id,
        "name": vendor.name,
        "rent_flagged": vendor.rent_flagged,
    }


@router.get("/vendors/{vendor_id}/rent-history")
async def vendor_rent_history(
    vendor_id: int,
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_any_staff_feature("role_manage_rent", "role_view_reports")),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    payments_result = await db.execute(
        select(RentPayment)
        .where(RentPayment.vendor_id == vendor_id)
        .order_by(RentPayment.period_month.desc())
    )
    payments = payments_result.scalars().all()

    legacy_result = await db.execute(
        select(LegacyFinancialHistory)
        .where(
            LegacyFinancialHistory.vendor_id == vendor_id,
            LegacyFinancialHistory.entry_type == "rent",
        )
        .order_by(
            LegacyFinancialHistory.entry_date.desc().nullslast(),
            LegacyFinancialHistory.imported_at.desc(),
        )
    )
    legacy_entries = legacy_result.scalars().all()

    today = date.today()
    latest = payments[0] if payments else None
    status = _rent_status(today, latest)

    return {
        "vendor": {
            "id": vendor.id,
            "name": vendor.name,
            "email": vendor.email,
            "phone": vendor.phone,
            "booth_number": vendor.booth_number or "—",
            "monthly_rent": float(vendor.monthly_rent or 0),
            "status": vendor.status,
            "role": vendor.role,
            "rent_flagged": vendor.rent_flagged,
            "rent_status": status,
        },
        "payments": [
            {
                "id": p.id,
                "amount": float(p.amount),
                "period_month": p.period_month.strftime("%B %Y"),
                "method": p.method,
                "status": p.status,
                "notes": p.notes,
                "processed_at": p.processed_at.isoformat() if p.processed_at else None,
            }
            for p in payments
        ],
        "legacy_entries": [_serialize_legacy_entry(entry) for entry in legacy_entries],
    }


@router.get("/reference-history")
async def reference_history(
    vendor_id: Optional[int] = None,
    entry_type: str = "rent",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_any_staff_feature("role_manage_rent", "role_view_reports")),
):
    if entry_type not in ("rent", "payout"):
        raise HTTPException(status_code=400, detail="entry_type must be 'rent' or 'payout'")
    limit = max(1, min(limit, 2000))

    query = (
        select(LegacyFinancialHistory)
        .options(selectinload(LegacyFinancialHistory.vendor))
        .where(LegacyFinancialHistory.entry_type == entry_type)
    )
    if vendor_id:
        query = query.where(LegacyFinancialHistory.vendor_id == vendor_id)
    if date_from:
        query = query.where(LegacyFinancialHistory.entry_date >= date_from)
    if date_to:
        query = query.where(LegacyFinancialHistory.entry_date <= date_to)
    query = query.order_by(
        LegacyFinancialHistory.entry_date.desc().nullslast(),
        LegacyFinancialHistory.imported_at.desc(),
    ).limit(limit)

    result = await db.execute(query)
    entries = result.scalars().all()

    return {
        "entries": [_serialize_legacy_entry(entry) for entry in entries],
        "entry_type": entry_type,
        "filters": {
            "vendor_id": vendor_id,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        "summary": {
            "count": len(entries),
            "total_amount": round(sum(float(entry.amount or 0) for entry in entries), 2),
        },
    }


@router.post("/vendors/{vendor_id}/record-rent")
async def record_rent_payment(
    vendor_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_manage_rent")),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    method = body.get("method", "cash")
    if method not in ("cash", "check", "card", "square"):
        raise HTTPException(status_code=400, detail="Invalid payment method.")

    amount = body.get("amount")
    if amount is not None:
        try:
            amount = Decimal(str(amount))
            if amount <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid amount.")
    else:
        amount = vendor.monthly_rent

    period_str = body.get("period")
    if period_str:
        try:
            parts = period_str.split("-")
            period = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid period. Use YYYY-MM.")
    else:
        today = date.today()
        period = date(today.year, today.month, 1)

    notes = body.get("notes", "")

    allocation = await apply_rent_payment(
        db=db,
        vendor=vendor,
        amount=amount,
        requested_period=period,
        method=method,
        notes=notes or f"Recorded by admin ({current_user.name})",
    )
    await db.commit()

    applied_periods = allocation["applied_periods"]
    credit_remainder = allocation["credit_remainder"]
    period_labels = ", ".join(p.strftime("%B %Y") for p in applied_periods)
    if applied_periods and credit_remainder > 0:
        message = (
            f"Recorded ${float(amount):.2f} for {vendor.name}. "
            f"Applied to {period_labels}. "
            f"Remaining credit ${float(credit_remainder):.2f} stays on the rent account."
        )
    elif applied_periods:
        message = (
            f"Recorded ${float(amount):.2f} for {vendor.name}. "
            f"Applied to {period_labels}."
        )
    else:
        message = (
            f"Recorded ${float(amount):.2f} for {vendor.name}. "
            f"No full month was covered yet; the full amount remains as rent credit."
        )

    return {
        "success": True,
        "message": message,
        "applied_periods": [p.isoformat() for p in applied_periods],
        "credit_remainder": float(credit_remainder),
        "rent_balance_after": float(allocation["rent_balance_after"]),
    }


@router.post("/vendors/{vendor_id}/rent-charge-card")
async def rent_charge_card(
    vendor_id: int,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_manage_rent")),
):
    result = await db.execute(select(Vendor).where(Vendor.id == vendor_id))
    vendor = result.scalar_one_or_none()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")

    amount = body.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid amount.")
    else:
        amount = float(vendor.monthly_rent or 0)

    if amount <= 0:
        raise HTTPException(status_code=400, detail="No rent amount to charge.")

    import math
    amount_cents = math.ceil(amount * 100)

    today = date.today()
    month_label = today.strftime("%B %Y")
    order_ref = f"RENT-{vendor_id}-{today.strftime('%Y%m')}"

    try:
        from app.services.poynt import create_terminal_order
        order_id = await create_terminal_order(
            amount_cents=amount_cents,
            currency="USD",
            order_ref=order_ref,
        )
        return {
            "poynt_order_id": order_id,
            "amount": amount,
            "vendor_name": vendor.name,
            "month": month_label,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to initiate card payment: {str(exc)}")


@router.get("/rent-charge-status/{poynt_order_id}")
async def rent_charge_status(
    poynt_order_id: str,
    current_user: Vendor = Depends(require_staff_feature("role_manage_rent")),
):
    try:
        from app.services.poynt import get_transaction_for_order
        result = await get_transaction_for_order(poynt_order_id)
        return {
            "status": result["status"],
            "transaction_id": result.get("transaction_id"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to check payment status: {str(exc)}")


@router.get("/payout-preview")
async def payout_preview(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_any_staff_feature("role_manage_rent", "role_view_reports")),
):
    today = date.today()
    period = date(today.year, today.month, 1)
    period_label = period.strftime("%B %Y")

    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active", Vendor.role == "vendor").order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    existing_payout = await db.execute(
        select(Payout).where(Payout.period_month == period).limit(1)
    )
    already_processed = existing_payout.scalar_one_or_none() is not None

    rows = []
    for v in vendors:
        bal_result = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == v.id)
        )
        bal = bal_result.scalar_one_or_none()
        gross = float(bal.balance) if bal else 0.0
        rent = float(v.monthly_rent or 0)

        rent_paid_result = await db.execute(
            select(RentPayment).where(
                RentPayment.vendor_id == v.id,
                RentPayment.period_month == period,
            )
        )
        rent_already_paid = rent_paid_result.scalar_one_or_none() is not None

        if rent_already_paid:
            rent_to_deduct = 0.0
        else:
            rent_to_deduct = rent

        if gross >= rent_to_deduct:
            remaining_after_rent = round(gross - rent_to_deduct, 2)
            if getattr(v, "auto_payout_enabled", True):
                net = remaining_after_rent
                carry_forward = 0.0
            else:
                net = 0.0
                carry_forward = remaining_after_rent
            shortfall = 0.0
        else:
            net = 0.0
            carry_forward = 0.0
            shortfall = round(rent_to_deduct - gross, 2)

        rows.append({
            "vendor_id": v.id,
            "name": v.name,
            "booth_number": v.booth_number or "—",
            "email": v.email or "",
            "gross_sales": round(gross, 2),
            "monthly_rent": rent,
            "rent_already_paid": rent_already_paid,
            "rent_to_deduct": round(rent_to_deduct, 2),
            "net_payout": net,
            "carry_forward": carry_forward,
            "shortfall": shortfall,
            "payout_method": v.payout_method or "—",
            "auto_payout_enabled": bool(getattr(v, "auto_payout_enabled", True)),
        })

    return {
        "period": period_label,
        "period_date": period.isoformat(),
        "already_processed": already_processed,
        "vendors": rows,
        "totals": {
            "gross_sales": round(sum(r["gross_sales"] for r in rows), 2),
            "rent_deducted": round(sum(r["rent_to_deduct"] for r in rows), 2),
            "net_payouts": round(sum(r["net_payout"] for r in rows), 2),
            "carry_forward": round(sum(r["carry_forward"] for r in rows), 2),
            "shortfalls": round(sum(r["shortfall"] for r in rows), 2),
        },
    }


@router.post("/process-payouts")
async def process_payouts(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_manage_rent")),
):
    today = date.today()
    period = date(today.year, today.month, 1)
    period_label = period.strftime("%B %Y")

    existing_payout = await db.execute(
        select(Payout).where(Payout.period_month == period).limit(1)
    )
    if existing_payout.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Payouts for {period_label} have already been processed.")

    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active", Vendor.role == "vendor").order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    processed = 0
    shortfall_count = 0
    total_net = Decimal("0")

    payout_emails_on = (await get_setting(db, "notify_payout")) == "true"
    rent_emails_on = (await get_setting(db, "notify_rent_due")) == "true"

    for v in vendors:
        bal_result = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == v.id)
        )
        bal = bal_result.scalar_one_or_none()
        sales = Decimal(str(bal.balance)) if bal and bal.balance else Decimal("0")
        rent_bal = Decimal(str(bal.rent_balance)) if bal and bal.rent_balance else Decimal("0")
        rent = Decimal(str(v.monthly_rent or 0))

        # ── Step 1: Deduct this month's rent from rent_balance ──
        rent_bal -= rent  # can go negative

        # ── Step 2: If rent_balance is negative, cover from sales_balance ──
        rent_covered_from_sales = Decimal("0")
        if rent_bal < 0 and sales > 0:
            transfer = min(sales, abs(rent_bal))
            rent_bal += transfer
            sales -= transfer
            rent_covered_from_sales = transfer

        # ── Step 3: Remaining sales_balance is either paid out or carried ──
        carry_balance = not bool(getattr(v, "auto_payout_enabled", True))
        if carry_balance:
            carry_forward = sales.quantize(Decimal("0.01"), ROUND_HALF_UP) if sales > 0 else Decimal("0")
            net = Decimal("0.00")
        else:
            net = sales.quantize(Decimal("0.01"), ROUND_HALF_UP) if sales > 0 else Decimal("0")
            carry_forward = Decimal("0.00")

        # Track shortfall (rent still owed after sales applied)
        shortfall = abs(rent_bal).quantize(Decimal("0.01"), ROUND_HALF_UP) if rent_bal < 0 else Decimal("0")
        if shortfall > 0:
            shortfall_count += 1

        # Total rent actually deducted from sales for the payout record
        total_rent_deducted = rent_covered_from_sales.quantize(Decimal("0.01"), ROUND_HALF_UP)

        payout = Payout(
            vendor_id=v.id,
            period_month=period,
            gross_sales=Decimal(str(bal.balance if bal else 0)).quantize(Decimal("0.01"), ROUND_HALF_UP),
            rent_deducted=total_rent_deducted,
            net_payout=net,
            payout_method=v.payout_method,
            zelle_handle=v.zelle_handle if hasattr(v, 'zelle_handle') else None,
            status="carried" if carry_balance else "pending",
            notes=(
                f"Processed by {current_user.name}"
                + (" | Balance carried forward" if carry_balance and carry_forward > 0 else "")
                + (f" | Shortfall: ${float(shortfall):.2f}" if shortfall > 0 else "")
            ),
        )
        db.add(payout)

        # Record rent deduction from balance as a rent payment if any was taken from sales
        if rent_covered_from_sales > 0:
            rent_payment = RentPayment(
                vendor_id=v.id,
                amount=rent_covered_from_sales,
                period_month=period,
                method="balance",
                status="paid",
                notes=f"Deducted from sales by {current_user.name}",
            )
            db.add(rent_payment)

        # ── Step 4: Update balances ──
        if bal:
            bal.balance = carry_forward if carry_balance else Decimal("0")
            bal.rent_balance = rent_bal.quantize(Decimal("0.01"), ROUND_HALF_UP)  # carries forward (may be negative)

        total_net += net
        processed += 1

        if v.email:
            try:
                if shortfall > 0 and rent_emails_on:
                    subj, html, plain = await rent_shortfall_email(
                        vendor_name=v.name or "Vendor",
                        gross_sales=float(gross),
                        rent_amount=float(rent),
                        shortfall=float(shortfall),
                        booth=v.booth_number or "—",
                        period=period_label,
                        db=db,
                    )
                    await send_email_safe(v.email, subj, html, plain)
                elif net > 0 and payout_emails_on and not carry_balance:
                    subj, html, plain = await payout_with_rent_email(
                        vendor_name=v.name or "Vendor",
                        gross_sales=float(gross),
                        rent_deducted=float(min(gross, rent_to_deduct)),
                        net_payout=float(net),
                        period=period_label,
                        method=v.payout_method or "TBD",
                        db=db,
                    )
                    await send_email_safe(v.email, subj, html, plain)
            except Exception as e:
                logger.warning(f"Failed to send payout email to {v.email}: {e}")

    await db.commit()

    return {
        "success": True,
        "message": f"Payouts processed for {period_label}.",
        "processed": processed,
        "shortfalls": shortfall_count,
        "total_net_payouts": float(total_net),
    }


@router.post("/send-rent-reminders")
async def send_rent_reminders(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_staff_feature("role_manage_rent")),
):
    rent_emails_on = (await get_setting(db, "notify_rent_due")) == "true"
    if not rent_emails_on:
        return {
            "success": True,
            "message": "Rent reminder emails are turned off in Settings > Notifications.",
            "sent_15_day": 0,
            "sent_27_day": 0,
            "skipped_no_email": 0,
        }

    today = date.today()
    current_period = date(today.year, today.month, 1)

    vendors_result = await db.execute(
        select(Vendor).where(
            Vendor.status == "active",
            Vendor.role == "vendor",
            Vendor.monthly_rent > 0,
        ).order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    sent_15 = 0
    sent_27 = 0
    skipped = 0

    for v in vendors:
        if not v.email:
            skipped += 1
            continue

        latest_result = await db.execute(
            select(RentPayment)
            .where(RentPayment.vendor_id == v.id)
            .order_by(RentPayment.period_month.desc())
            .limit(1)
        )
        latest = latest_result.scalar_one_or_none()

        if latest and latest.period_month >= current_period:
            continue

        if latest:
            days_overdue = (today - latest.period_month).days
        else:
            days_overdue = 999

        rent_amount = float(v.monthly_rent or 0)
        booth = v.booth_number or "—"
        period_label = current_period.strftime("%B %Y")

        if days_overdue >= 27:
            subj, html, plain = await rent_overdue_27day_email(
                vendor_name=v.name or "Vendor",
                amount=rent_amount,
                booth=booth,
                period=period_label,
                db=db,
            )
            await send_email_safe(v.email, subj, html, plain)
            sent_27 += 1
        elif days_overdue >= 15:
            subj, html, plain = await rent_overdue_15day_email(
                vendor_name=v.name or "Vendor",
                amount=rent_amount,
                booth=booth,
                period=period_label,
                db=db,
            )
            await send_email_safe(v.email, subj, html, plain)
            sent_15 += 1

    return {
        "success": True,
        "message": f"Rent reminders sent: {sent_15} at 15 days, {sent_27} at 27 days.",
        "sent_15_day": sent_15,
        "sent_27_day": sent_27,
        "skipped_no_email": skipped,
    }


@router.post("/send-weekly-reports")
async def send_weekly_reports(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    today = date.today()
    week_start = today - timedelta(days=7)
    period_label = f"{week_start.strftime('%-m/%-d')} – {today.strftime('%-m/%-d/%Y')}"

    from datetime import timezone as tz
    from app.timezone import STORE_TZ
    cst = STORE_TZ
    start_utc = datetime(week_start.year, week_start.month, week_start.day, tzinfo=cst).astimezone(tz.utc)
    end_utc = datetime(today.year, today.month, today.day, tzinfo=cst).astimezone(tz.utc) + timedelta(days=1)

    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active", Vendor.role == "vendor").order_by(Vendor.name)
    )
    vendors = vendors_result.scalars().all()

    sent = 0
    skipped = 0

    for v in vendors:
        if not v.email:
            skipped += 1
            continue

        sales_result = await db.execute(
            select(func.count(SaleItem.id), func.coalesce(func.sum(SaleItem.line_total), 0))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(
                SaleItem.vendor_id == v.id,
                Sale.is_voided == False,
                Sale.created_at >= start_utc,
                Sale.created_at < end_utc,
            )
        )
        row = sales_result.one()
        items_sold = row[0] or 0
        total_sales = float(row[1] or 0)

        bal_result = await db.execute(
            select(VendorBalance.balance).where(VendorBalance.vendor_id == v.id)
        )
        current_balance = float(bal_result.scalar_one_or_none() or 0)

        active_result = await db.execute(
            select(func.count(Item.id)).where(Item.vendor_id == v.id, Item.status == "active")
        )
        active_items = active_result.scalar_one() or 0

        await notify_weekly_report(
            db, v, period_label,
            total_sales, items_sold, current_balance, active_items,
        )
        sent += 1

    return {
        "success": True,
        "message": f"Weekly reports sent to {sent} vendors.",
        "sent": sent,
        "skipped_no_email": skipped,
    }


@router.post("/reset-data")
async def reset_data(
    confirm: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    admin: Vendor = Depends(require_admin),
):
    if confirm != "CLEAR ALL DATA":
        raise HTTPException(status_code=400, detail="Type 'CLEAR ALL DATA' to confirm")

    admin_ids = []
    result = await db.execute(
        select(Vendor.id).where(Vendor.role.in_(["admin", "cashier"]))
    )
    admin_ids = [row[0] for row in result.fetchall()]

    if not admin_ids:
        raise HTTPException(status_code=500, detail="No admin/cashier accounts found")

    await db.execute(delete(BoothShowcase))
    await db.execute(delete(ClassRegistration))
    await db.execute(delete(StudioImage))
    await db.execute(delete(StudioClass))
    await db.execute(delete(Reservation))
    await db.execute(delete(GiftCardTransaction))
    await db.execute(delete(GiftCard))
    await db.execute(delete(SaleItem))
    await db.execute(delete(Sale))
    await db.execute(delete(ItemImage))
    await db.execute(delete(Item))
    await db.execute(delete(Payout))
    await db.execute(delete(RentPayment))
    await db.execute(delete(BalanceAdjustment))
    await db.execute(delete(VendorBalance).where(VendorBalance.vendor_id.notin_(admin_ids)))
    await db.execute(delete(Vendor).where(Vendor.id.notin_(admin_ids)))

    for aid in admin_ids:
        existing = await db.execute(
            select(VendorBalance).where(VendorBalance.vendor_id == aid)
        )
        bal = existing.scalar_one_or_none()
        if bal:
            bal.balance = Decimal("0.00")
        else:
            db.add(VendorBalance(vendor_id=aid, balance=Decimal("0.00")))

    await db.execute(text("SELECT setval('vendors_id_seq', (SELECT COALESCE(MAX(id),0) FROM vendors))"))
    await db.execute(text("SELECT setval('items_id_seq', 1, false)"))

    await db.commit()

    remaining = await db.execute(select(func.count()).select_from(Vendor))
    vendor_count = remaining.scalar()

    return {
        "success": True,
        "message": f"All data cleared. {vendor_count} system accounts preserved (admin/cashier).",
        "preserved_accounts": admin_ids,
    }


# ─── Rent & Payouts combined transaction ledger ───────────────────────────
@router.get("/rent-payout-ledger")
async def rent_payout_ledger(
    db: AsyncSession = Depends(get_db),
    _: Vendor = Depends(require_any_staff_feature("role_manage_rent", "role_view_reports")),
):
    """
    Returns a combined list of all rent payments and payouts,
    plus summary stats and per-vendor balance cards.
    """
    from sqlalchemy.orm import selectinload

    today = date.today()
    current_period = date(today.year, today.month, 1)

    # ── Rent payments (all time) ──
    rent_result = await db.execute(
        select(RentPayment)
        .options(selectinload(RentPayment.vendor))
        .order_by(RentPayment.processed_at.desc())
    )
    rent_payments = rent_result.scalars().all()

    # ── Payouts (all time) ──
    payout_result = await db.execute(
        select(Payout)
        .options(selectinload(Payout.vendor))
        .order_by(Payout.created_at.desc())
    )
    payouts = payout_result.scalars().all()

    # ── Active vendors with rent ──
    vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active", Vendor.role == "vendor", Vendor.monthly_rent > 0)
    )
    active_rent_vendors = vendors_result.scalars().all()

    # ── All vendor balances ──
    bal_result = await db.execute(select(VendorBalance))
    balances = {}
    rent_balances = {}
    for b in bal_result.scalars().all():
        balances[b.vendor_id] = float(b.balance) if b.balance is not None else 0.0
        rent_balances[b.vendor_id] = float(b.rent_balance) if b.rent_balance is not None else 0.0

    paid_current_period = {
        rp.vendor_id
        for rp in rent_payments
        if rp.period_month == current_period and rp.status == "paid"
    }

    # ── All active vendors for balance cards ──
    all_vendors_result = await db.execute(
        select(Vendor).where(Vendor.status == "active", Vendor.role == "vendor").order_by(Vendor.name)
    )
    all_vendors = all_vendors_result.scalars().all()

    # ── Build combined transactions list ──
    transactions = []

    for rp in rent_payments:
        transactions.append({
            "type": "rent",
            "date": rp.processed_at.isoformat() if rp.processed_at else None,
            "vendor_name": rp.vendor.name if rp.vendor else "Unknown",
            "vendor_id": rp.vendor_id,
            "amount": float(rp.amount),
            "method": rp.method or "",
            "period": rp.period_month.strftime("%Y-%m") if rp.period_month else "",
            "status": rp.status,
            "notes": rp.notes or "",
        })

    for p in payouts:
        transactions.append({
            "type": "payout",
            "date": p.created_at.isoformat() if p.created_at else None,
            "vendor_name": p.vendor.name if p.vendor else "Unknown",
            "vendor_id": p.vendor_id,
            "amount": float(p.net_payout),
            "method": p.payout_method or "check",
            "period": p.period_month.strftime("%Y-%m") if p.period_month else "",
            "status": p.status,
            "notes": p.notes or "",
        })

    # Sort by date descending
    transactions.sort(key=lambda t: t["date"] or "", reverse=True)

    # ── Summary stats ──
    # Current month rent
    current_month_paid_ids = set()
    rent_collected_this_month = 0.0
    for rp in rent_payments:
        if rp.period_month and rp.period_month >= current_period and rp.status == "paid":
            rent_collected_this_month += float(rp.amount)
            current_month_paid_ids.add(rp.vendor_id)

    total_rent_owed = sum(float(v.monthly_rent) for v in active_rent_vendors)
    rent_outstanding = sum(
        float(v.monthly_rent) for v in active_rent_vendors
        if v.id not in current_month_paid_ids
    )

    # Payouts
    total_payouts_processed = sum(
        float(p.net_payout) for p in payouts if p.status in ("paid", "completed")
    )
    total_payouts_pending = sum(
        float(p.net_payout) for p in payouts if p.status == "pending"
    )

    # Total vendor balances headline uses projected post-rent position.
    total_sales_balances = sum(balances.get(v.id, 0.0) for v in all_vendors)
    total_rent_balances = round(
        sum(_admin_display_rent_balance(rent_balances.get(v.id, 0.0), float(v.monthly_rent or 0), v.id in paid_current_period) for v in all_vendors),
        2,
    )
    total_balances = round(
        sum(_admin_next_rent_projection(balances.get(v.id, 0.0), float(v.monthly_rent or 0)) for v in all_vendors),
        2,
    )

    # ── Per-vendor balance cards ──
    vendor_cards = []
    for v in all_vendors:
        sb = balances.get(v.id, 0.0)
        rb = rent_balances.get(v.id, 0.0)
        rent = float(v.monthly_rent or 0)
        rb_disp = _admin_display_rent_balance(rb, rent, v.id in paid_current_period)
        combined = _admin_next_rent_projection(sb, rent)
        vendor_cards.append({
            "id": v.id,
            "name": v.name,
            "booth_number": v.booth_number or "—",
            "balance": combined,
            "sales_balance": round(sb, 2),
            "rent_balance": rb_disp,
            "combined_balance": combined,
        })

    return {
        "summary": {
            "total_rent_owed": round(total_rent_owed, 2),
            "rent_collected_this_month": round(rent_collected_this_month, 2),
            "rent_outstanding": round(rent_outstanding, 2),
            "total_payouts_processed": round(total_payouts_processed, 2),
            "total_payouts_pending": round(total_payouts_pending, 2),
            "total_vendor_balances": round(total_balances, 2),
            "total_sales_balances": round(total_sales_balances, 2),
            "total_rent_balances": round(total_rent_balances, 2),
            "month_label": today.strftime("%B %Y"),
        },
        "vendor_cards": vendor_cards,
        "transactions": transactions,
    }
