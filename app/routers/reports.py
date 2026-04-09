import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, extract, cast, Date
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.sale import Sale, SaleItem
from app.models.vendor import Vendor
from app.models.rent import RentPayment
from app.models.payout import Payout
from app.models.reservation import Reservation
from app.models.item import Item
from app.routers.auth import require_admin
from app.routers.settings import require_staff_feature
from app.timezone import STORE_TZ

router = APIRouter(prefix="/admin/reports", tags=["reports"])


def _local_today():
    return datetime.now(STORE_TZ).date()


def _local_date_to_utc_range(d: date) -> tuple[datetime, datetime]:
    start_local = datetime(d.year, d.month, d.day, tzinfo=STORE_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(STORE_TZ)


def _parse_dates(from_date, to_date):
    try:
        start_date = date.fromisoformat(from_date) if from_date else _local_today()
        end_date = date.fromisoformat(to_date) if to_date else _local_today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    start_utc, _ = _local_date_to_utc_range(start_date)
    _, end_utc = _local_date_to_utc_range(end_date)
    return start_utc, end_utc


@router.get("/dashboard")
async def dashboard_stats(
    period: Optional[str] = Query("today"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    today = _local_today()

    if period == "week":
        start_date = today - timedelta(days=today.weekday())
    elif period == "month":
        start_date = date(today.year, today.month, 1)
    else:
        start_date = today

    start_dt, _ = _local_date_to_utc_range(start_date)
    _, end_dt = _local_date_to_utc_range(today)

    result = await db.execute(
        select(Sale)
        .options(selectinload(Sale.items))
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .order_by(Sale.created_at.desc())
    )
    sales = result.scalars().all()

    total_transactions = len(sales)
    total_revenue = sum(float(s.total) for s in sales)
    total_tax = sum(float(s.tax_amount) for s in sales)
    total_items_sold = sum(
        sum(si.quantity for si in s.items) if s.items else 0
        for s in sales
    )
    avg_transaction = round(total_revenue / total_transactions, 2) if total_transactions > 0 else 0

    hourly_sales = {}
    for s in sales:
        if s.created_at:
            local_dt = _to_local(s.created_at)
            hour = local_dt.hour
            hourly_sales[hour] = hourly_sales.get(hour, 0) + float(s.total)

    hourly_data = []
    for h in range(8, 22):
        hourly_data.append({"hour": h, "label": _format_hour(h), "total": round(hourly_sales.get(h, 0), 2)})

    vendor_result = await db.execute(
        select(
            Vendor.name,
            Vendor.booth_number,
            func.coalesce(func.sum(SaleItem.line_total), 0).label("total_sales"),
            func.coalesce(func.sum(SaleItem.quantity), 0).label("items_sold"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Vendor, Vendor.id == SaleItem.vendor_id)
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .group_by(Vendor.name, Vendor.booth_number)
        .order_by(func.sum(SaleItem.line_total).desc())
        .limit(10)
    )
    top_vendors = [
        {
            "vendor_name": r.name,
            "booth_number": r.booth_number or "",
            "total_sales": round(float(r.total_sales), 2),
            "items_sold": int(r.items_sold),
        }
        for r in vendor_result.all()
    ]

    thirty_ago = today - timedelta(days=29)
    thirty_start_utc, _ = _local_date_to_utc_range(thirty_ago)
    daily_result = await db.execute(
        select(Sale)
        .where(Sale.created_at >= thirty_start_utc)
        .order_by(Sale.created_at)
    )
    daily_sales_raw = daily_result.scalars().all()

    daily_map: dict[str, dict] = {}
    for s in daily_sales_raw:
        if s.created_at:
            local_date_str = str(_to_local(s.created_at).date())
            if local_date_str not in daily_map:
                daily_map[local_date_str] = {"count": 0, "total": 0}
            daily_map[local_date_str]["count"] += 1
            daily_map[local_date_str]["total"] = round(daily_map[local_date_str]["total"] + float(s.total), 2)

    daily_sales = []
    for i in range(30):
        d = thirty_ago + timedelta(days=i)
        ds = str(d)
        daily_sales.append({
            "date": ds,
            "label": d.strftime("%-m/%d"),
            "count": daily_map.get(ds, {}).get("count", 0),
            "total": daily_map.get(ds, {}).get("total", 0),
        })

    payment_result = await db.execute(
        select(
            Sale.payment_method,
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.total), 0).label("total"),
        )
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .group_by(Sale.payment_method)
    )
    payment_methods = [
        {"method": r.payment_method or "unknown", "count": r.count, "total": round(float(r.total), 2)}
        for r in payment_result.all()
    ]

    vendor_count_result = await db.execute(
        select(func.count(Vendor.id)).where(Vendor.role == "vendor", Vendor.is_active == True)
    )
    total_vendors = vendor_count_result.scalar() or 0

    item_count_result = await db.execute(
        select(func.count(Item.id)).where(Item.status == "active")
    )
    total_inventory = item_count_result.scalar() or 0

    return {
        "period": period,
        "start_date": str(start_date),
        "end_date": str(today),
        "summary": {
            "total_revenue": round(total_revenue, 2),
            "total_transactions": total_transactions,
            "total_items_sold": total_items_sold,
            "total_tax": round(total_tax, 2),
            "avg_transaction": avg_transaction,
            "net_sales": round(total_revenue - total_tax, 2),
        },
        "total_vendors": total_vendors,
        "total_inventory": total_inventory,
        "hourly_sales": hourly_data,
        "daily_sales": daily_sales,
        "top_vendors": top_vendors,
        "payment_methods": payment_methods,
    }


def _format_hour(h):
    if h == 0:
        return "12 AM"
    elif h < 12:
        return f"{h} AM"
    elif h == 12:
        return "12 PM"
    else:
        return f"{h - 12} PM"


@router.get("/daily_sales")
async def report_daily_sales(
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    start_dt, end_dt = _parse_dates(from_date or start, to_date or end)

    result = await db.execute(
        select(Sale)
        .options(selectinload(Sale.cashier), selectinload(Sale.items))
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .order_by(Sale.created_at.desc())
    )
    sales = result.scalars().all()

    total_transactions = len(sales)
    total_revenue = sum(float(s.total) for s in sales)
    total_tax = sum(float(s.tax_amount) for s in sales)
    total_items_sold = sum(sum(si.quantity for si in s.items) if s.items else 0 for s in sales)
    avg_transaction = round(total_revenue / total_transactions, 2) if total_transactions > 0 else 0

    rows = []
    for s in sales:
        item_count = sum(si.quantity for si in s.items) if s.items else 0
        rows.append({
            "date": _to_local(s.created_at).strftime("%Y-%m-%d %I:%M %p") if s.created_at else "",
            "cashier": s.cashier.name if s.cashier else "Unknown",
            "items": item_count,
            "subtotal": round(float(s.subtotal), 2),
            "tax": round(float(s.tax_amount), 2),
            "total": round(float(s.total), 2),
            "payment": s.payment_method or "unknown",
        })

    return {
        "summary": {
            "total_revenue": round(total_revenue, 2),
            "total_transactions": total_transactions,
            "total_items_sold": total_items_sold,
            "total_tax": round(total_tax, 2),
            "avg_transaction": avg_transaction,
        },
        "columns": ["date", "cashier", "items", "subtotal", "tax", "total", "payment"],
        "rows": rows,
    }


@router.get("/sales")
async def report_sales(
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    start_dt, end_dt = _parse_dates(from_date or start, to_date or end)

    result = await db.execute(
        select(Sale)
        .options(selectinload(Sale.cashier), selectinload(Sale.items))
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
            "date": _to_local(s.created_at).isoformat() if s.created_at else None,
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


@router.get("/vendor_performance")
async def report_vendor_performance(
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    start_dt, end_dt = _parse_dates(from_date or start, to_date or end)

    result = await db.execute(
        select(
            Vendor.name,
            Vendor.booth_number,
            func.coalesce(func.sum(SaleItem.line_total), 0).label("total_sales"),
            func.coalesce(func.sum(SaleItem.quantity), 0).label("items_sold"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Vendor, Vendor.id == SaleItem.vendor_id)
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .group_by(Vendor.name, Vendor.booth_number)
        .order_by(func.sum(SaleItem.line_total).desc())
    )
    rows = result.all()

    grand_total = sum(float(r.total_sales) for r in rows)

    vendor_rows = []
    for r in rows:
        total_sales = float(r.total_sales)
        vendor_rows.append({
            "vendor_name": r.name,
            "booth": r.booth_number or "",
            "items_sold": int(r.items_sold),
            "total_sales": round(total_sales, 2),
            "revenue_pct": round(total_sales / grand_total * 100, 1) if grand_total > 0 else 0,
        })

    return {
        "summary": {
            "active_vendors": len(vendor_rows),
            "total_vendor_sales": round(grand_total, 2),
            "avg_vendor_sales": round(grand_total / len(vendor_rows), 2) if vendor_rows else 0,
        },
        "columns": ["vendor_name", "booth", "items_sold", "total_sales", "revenue_pct"],
        "rows": vendor_rows,
    }


@router.get("/vendors")
async def report_vendors(
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    start_dt, end_dt = _parse_dates(from_date or start, to_date or end)

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


@router.get("/top_items")
async def report_top_items(
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    start_dt, end_dt = _parse_dates(from_date, to_date)

    result = await db.execute(
        select(
            Item.name.label("item_name"),
            Vendor.name.label("vendor_name"),
            func.coalesce(func.sum(SaleItem.quantity), 0).label("qty_sold"),
            func.coalesce(func.sum(SaleItem.line_total), 0).label("revenue"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Item, Item.id == SaleItem.item_id)
        .outerjoin(Vendor, Vendor.id == SaleItem.vendor_id)
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .group_by(Item.name, Vendor.name)
        .order_by(func.sum(SaleItem.quantity).desc())
        .limit(50)
    )
    rows = result.all()

    total_qty = sum(int(r.qty_sold) for r in rows)
    total_rev = sum(float(r.revenue) for r in rows)

    item_rows = []
    for r in rows:
        item_rows.append({
            "item_name": r.item_name or "Unknown",
            "vendor": r.vendor_name or "",
            "qty_sold": int(r.qty_sold),
            "revenue": round(float(r.revenue), 2),
        })

    return {
        "summary": {
            "unique_items": len(item_rows),
            "total_quantity": total_qty,
            "total_item_revenue": round(total_rev, 2),
        },
        "columns": ["item_name", "vendor", "qty_sold", "revenue"],
        "rows": item_rows,
    }


@router.get("/hourly_sales")
async def report_hourly_sales(
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    start_dt, end_dt = _parse_dates(from_date, to_date)

    result = await db.execute(
        select(Sale)
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
    )
    sales = result.scalars().all()

    hourly = {}
    for s in sales:
        if s.created_at:
            h = _to_local(s.created_at).hour
            if h not in hourly:
                hourly[h] = {"count": 0, "total": 0}
            hourly[h]["count"] += 1
            hourly[h]["total"] += float(s.total)

    rows = []
    for h in range(24):
        if h in hourly:
            rows.append({
                "hour": _format_hour(h),
                "transactions": hourly[h]["count"],
                "total_sales": round(hourly[h]["total"], 2),
            })

    return {
        "summary": {
            "total_transactions": len(sales),
            "total_amount": round(sum(float(s.total) for s in sales), 2),
        },
        "columns": ["hour", "transactions", "total_sales"],
        "rows": rows,
    }


@router.get("/payment_methods")
async def report_payment_methods(
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    start_dt, end_dt = _parse_dates(from_date, to_date)

    result = await db.execute(
        select(
            Sale.payment_method,
            func.count(Sale.id).label("count"),
            func.coalesce(func.sum(Sale.total), 0).label("total"),
        )
        .where(Sale.created_at >= start_dt, Sale.created_at < end_dt)
        .group_by(Sale.payment_method)
        .order_by(func.sum(Sale.total).desc())
    )
    rows = result.all()

    total_amount = sum(float(r.total) for r in rows)
    total_txns = sum(r.count for r in rows)

    method_rows = []
    for r in rows:
        method_rows.append({
            "method": (r.payment_method or "unknown").title(),
            "transactions": r.count,
            "total_amount": round(float(r.total), 2),
            "pct": round(float(r.total) / total_amount * 100, 1) if total_amount > 0 else 0,
        })

    return {
        "summary": {
            "total_transactions": total_txns,
            "total_amount": round(total_amount, 2),
        },
        "columns": ["method", "transactions", "total_amount", "pct"],
        "rows": method_rows,
    }


@router.get("/vendor_balances")
async def report_vendor_balances(
    from_date: Optional[str] = Query(None, alias="from_date"),
    to_date: Optional[str] = Query(None, alias="to_date"),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    from app.models.vendor import VendorBalance
    from app.models.rent import RentPayment as RP

    result = await db.execute(
        select(Vendor)
        .where(Vendor.status == "active")
        .order_by(Vendor.name)
    )
    vendors = result.scalars().all()

    # Fetch balances
    bal_result = await db.execute(
        select(VendorBalance.vendor_id, VendorBalance.balance, VendorBalance.rent_balance)
    )
    sb_map = {}
    rb_map = {}
    for row in bal_result.all():
        sb_map[row.vendor_id] = float(row.balance or 0)
        rb_map[row.vendor_id] = float(row.rent_balance or 0)

    # Check rent paid this month
    today = date.today()
    current_period = date(today.year, today.month, 1)
    rp_result = await db.execute(
        select(RP.vendor_id, RP.status).where(RP.period_month == current_period)
    )
    paid_ids = {row.vendor_id for row in rp_result.all() if row.status == "paid"}

    rows = []
    total_net = 0
    for v in vendors:
        if v.role != "vendor":
            continue
        sb = sb_map.get(v.id, 0.0)
        rb = rb_map.get(v.id, 0.0)
        rent = float(v.monthly_rent or 0)
        rent_paid = v.id in paid_ids
        if rent > 0 and not rent_paid:
            net_payout = round(sb - rent + rb, 2)
        else:
            net_payout = round(sb + rb, 2)
        total_net += net_payout
        rows.append({
            "vendor_name": v.name,
            "booth": v.booth_number or "",
            "total_sales": round(sb, 2),
            "rent_due": round(rent, 2),
            "net_payout": net_payout,
            "rent_paid_this_month": rent_paid,
            "status": v.status,
        })

    avg_net = round(total_net / len(rows), 2) if rows else 0

    return {
        "summary": {
            "total_vendors": len(rows),
            "total_net_payout": round(total_net, 2),
            "avg_net_payout": avg_net,
        },
        "columns": ["vendor_name", "booth", "total_sales", "rent_due", "net_payout", "status"],
        "rows": rows,
    }


@router.get("/rent")
async def report_rent(
    month: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
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

    result = await db.execute(
        select(RentPayment)
        .options(selectinload(RentPayment.vendor))
        .where(RentPayment.period_month == target_month)
        .order_by(RentPayment.processed_at.desc())
    )
    payments = result.scalars().all()

    paid_vendor_ids = {p.vendor_id for p in payments}

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
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
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
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
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
            "customer_email": r.customer_email or "",
            "item_name": r.item.name if r.item else "Unknown",
            "amount_paid": float(r.amount_paid) if r.amount_paid else 0,
            "date": _to_local(r.created_at).isoformat() if r.created_at else None,
            "status": r.status,
        })

    return {"reservations": reservations_list}


@router.post("/reservations/{reservation_id}/ready")
async def mark_reservation_ready(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
):
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Reservation).options(selectinload(Reservation.item))
        .where(Reservation.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if reservation.status == "completed":
        raise HTTPException(status_code=400, detail="Order already completed")
    if reservation.status == "ready":
        return {"message": "Order is already marked as ready for pickup", "email_sent": False}

    reservation.status = "ready"
    await db.commit()

    email_sent = False
    if reservation.customer_email:
        try:
            from app.routers.notifications import _is_notification_enabled
            if await _is_notification_enabled(db, "notify_order_ready_pickup"):
                from app.services.email_templates import order_ready_pickup_email
                from app.services.email import send_email_safe

                hours_keys = [
                    ("Monday", "hours_monday"), ("Tuesday", "hours_tuesday"),
                    ("Wednesday", "hours_wednesday"), ("Thursday", "hours_thursday"),
                    ("Friday", "hours_friday"), ("Saturday", "hours_saturday"),
                    ("Sunday", "hours_sunday"),
                ]
                from app.models.store_setting import StoreSetting
                hours_lines = []
                for day, key in hours_keys:
                    r = await db.execute(
                        select(StoreSetting.value).where(StoreSetting.key == key)
                    )
                    val = r.scalar_one_or_none() or "Closed"
                    hours_lines.append(f"{day}: {val}")
                store_hours = "\n".join(hours_lines)

                item_name = reservation.item.name if reservation.item else "your item"
                subject, html_body, plain_body = await order_ready_pickup_email(
                    customer_name=reservation.customer_name or "Customer",
                    item_name=item_name,
                    store_hours=store_hours,
                    db=db,
                )
                await send_email_safe(reservation.customer_email, subject, html_body, plain_body)
                email_sent = True
        except Exception as e:
            logger.warning(f"Failed to send ready-for-pickup email: {e}")

    msg = "Order marked as ready for pickup"
    if email_sent:
        msg += " — pickup notification email sent"
    elif reservation.customer_email:
        msg += " — email notification failed"
    else:
        msg += " (no customer email on file)"

    return {"message": msg, "email_sent": email_sent}


@router.post("/reservations/{reservation_id}/pickup")
async def mark_reservation_pickup(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
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
