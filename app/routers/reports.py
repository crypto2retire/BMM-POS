from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.sale import Sale, SaleItem
from app.models.vendor import Vendor
from app.models.rent import RentPayment
from app.models.payout import Payout
from app.models.reservation import Reservation
from app.models.item import Item
from app.routers.auth import require_cashier_or_admin, require_admin

router = APIRouter(prefix="/admin/reports", tags=["reports"])


@router.get("/sales")
async def report_sales(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_cashier_or_admin),
):
    try:
        start_date = date.fromisoformat(start) if start else date.today()
        end_date = date.fromisoformat(end) if end else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    end_dt = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)
    start_dt = datetime(start_date.year, start_date.month, start_date.day)

    result = await db.execute(
        select(Sale)
        .options(
            selectinload(Sale.cashier),
            selectinload(Sale.items),
        )
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .order_by(Sale.created_at.desc())
    )
    sales = result.scalars().all()

    total_transactions = len(sales)
    total_revenue = sum(float(s.total) for s in sales)
    total_tax = sum(float(s.tax_amount) for s in sales)

    sales_list = []
    for s in sales:
        item_count = sum(si.quantity for si in s.items) if s.items else 0
        sales_list.append({
            "id": s.id,
            "date": s.created_at.isoformat() if s.created_at else None,
            "cashier_name": s.cashier.name if s.cashier else "Unknown",
            "item_count": item_count,
            "subtotal": float(s.subtotal),
            "tax_amount": float(s.tax_amount),
            "total": float(s.total),
            "payment_method": s.payment_method,
        })

    return {
        "summary": {
            "total_transactions": total_transactions,
            "total_revenue": round(total_revenue, 2),
            "total_tax": round(total_tax, 2),
        },
        "sales": sales_list,
    }


@router.get("/vendors")
async def report_vendors(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_cashier_or_admin),
):
    try:
        start_date = date.fromisoformat(start) if start else date.today()
        end_date = date.fromisoformat(end) if end else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    end_dt = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)
    start_dt = datetime(start_date.year, start_date.month, start_date.day)

    result = await db.execute(
        select(
            SaleItem.vendor_id,
            Vendor.name,
            Vendor.booth_number,
            func.coalesce(func.sum(SaleItem.line_total), 0).label("total_sales"),
            func.coalesce(func.sum(SaleItem.quantity), 0).label("items_sold"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Vendor, Vendor.id == SaleItem.vendor_id)
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .group_by(SaleItem.vendor_id, Vendor.name, Vendor.booth_number)
        .order_by(func.sum(SaleItem.line_total).desc())
    )
    rows = result.all()

    grand_total = sum(float(r.total_sales) for r in rows)

    vendors_list = []
    for r in rows:
        total_sales = float(r.total_sales)
        vendors_list.append({
            "vendor_name": r.name,
            "booth_number": r.booth_number or "",
            "total_sales": round(total_sales, 2),
            "items_sold": int(r.items_sold),
            "revenue_pct": round(total_sales / grand_total * 100, 1) if grand_total > 0 else 0,
        })

    return {"vendors": vendors_list}


@router.get("/rent")
async def report_rent(
    month: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_cashier_or_admin),
):
    try:
        if month:
            parts = month.split("-")
            target_month = date(int(parts[0]), int(parts[1]), 1)
        else:
            today = date.today()
            target_month = date(today.year, today.month, 1)
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM.")

    # Get rent payments for the month
    result = await db.execute(
        select(RentPayment)
        .options(selectinload(RentPayment.vendor))
        .where(RentPayment.period_month == target_month)
        .order_by(RentPayment.processed_at.desc())
    )
    payments = result.scalars().all()

    paid_vendor_ids = {p.vendor_id for p in payments}

    # Get vendors with rent > 0 who have no payment for this month
    result = await db.execute(
        select(Vendor)
        .where(Vendor.monthly_rent > 0, Vendor.status == "active")
    )
    all_rent_vendors = result.scalars().all()

    total_collected = sum(float(p.amount) for p in payments if p.status == "paid")
    total_outstanding = sum(
        float(v.monthly_rent) for v in all_rent_vendors if v.id not in paid_vendor_ids
    )

    payments_list = []
    for p in payments:
        payments_list.append({
            "vendor_name": p.vendor.name if p.vendor else "Unknown",
            "booth_number": p.vendor.booth_number if p.vendor else "",
            "rent_amount": float(p.amount),
            "date_paid": p.processed_at.isoformat() if p.processed_at else None,
            "method": p.method,
            "status": p.status,
        })

    # Add outstanding vendors
    for v in all_rent_vendors:
        if v.id not in paid_vendor_ids:
            payments_list.append({
                "vendor_name": v.name,
                "booth_number": v.booth_number or "",
                "rent_amount": float(v.monthly_rent),
                "date_paid": None,
                "method": "",
                "status": "outstanding",
            })

    return {
        "summary": {
            "total_collected": round(total_collected, 2),
            "total_outstanding": round(total_outstanding, 2),
        },
        "payments": payments_list,
    }


@router.get("/payouts")
async def report_payouts(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_cashier_or_admin),
):
    result = await db.execute(
        select(Payout)
        .options(selectinload(Payout.vendor))
        .order_by(Payout.created_at.desc())
    )
    payouts = result.scalars().all()

    payouts_list = []
    for p in payouts:
        payouts_list.append({
            "vendor_name": p.vendor.name if p.vendor else "Unknown",
            "period_month": p.period_month.isoformat() if p.period_month else None,
            "gross_sales": float(p.gross_sales),
            "rent_deducted": float(p.rent_deducted),
            "net_payout": float(p.net_payout),
            "status": p.status,
        })

    return {"payouts": payouts_list}


@router.get("/reservations")
async def report_reservations(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_cashier_or_admin),
):
    result = await db.execute(
        select(Reservation)
        .options(selectinload(Reservation.item))
        .order_by(Reservation.created_at.desc())
    )
    reservations = result.scalars().all()

    reservations_list = []
    for r in reservations:
        reservations_list.append({
            "id": r.id,
            "customer_name": r.customer_name or "",
            "customer_phone": r.customer_phone or "",
            "item_name": r.item.name if r.item else "Unknown",
            "amount_paid": float(r.amount_paid) if r.amount_paid else 0,
            "date": r.created_at.isoformat() if r.created_at else None,
            "status": r.status,
        })

    return {"reservations": reservations_list}


@router.post("/reservations/{reservation_id}/pickup")
async def mark_reservation_pickup(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_cashier_or_admin),
):
    result = await db.execute(
        select(Reservation).where(Reservation.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    reservation.status = "completed"
    await db.commit()

    return {"message": "Reservation marked as picked up"}
