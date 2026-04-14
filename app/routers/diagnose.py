"""Admin endpoint for balance diagnostics. Mounted on /api/v1/admin/diagnose-balances."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.models.vendor import Vendor
from app.routers.auth import get_current_user
from app.routers.settings import role_feature_allowed

router = APIRouter(tags=["admin"])


@router.get("/admin/diagnose-balances")
async def diagnose_balances(
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    if current_user.role not in ("admin",):
        return {"error": "Admin only"}

    result = {}

    # 1. Current vendor balances
    vendors = await db.execute(text("""
        SELECT v.id, v.name, v.booth_number, v.commission_rate, v.consignment_rate,
               v.monthly_rent, v.landing_page_fee,
               COALESCE(vb.balance, 0) as balance,
               COALESCE(vb.rent_balance, 0) as rent_balance
        FROM vendors v
        LEFT JOIN vendor_balances vb ON vb.vendor_id = v.id
        WHERE v.role = 'vendor'
        ORDER BY v.name
    """))
    result["vendor_balances"] = [
        {
            "id": r.id, "name": r.name, "booth": r.booth_number,
            "balance": float(r.balance), "rent_balance": float(r.rent_balance),
            "commission_rate": float(r.commission_rate),
            "consignment_rate": float(r.consignment_rate),
            "monthly_rent": float(r.monthly_rent or 0),
        }
        for r in vendors.fetchall()
    ]

    # 2. All-time sales per vendor
    sales = await db.execute(text("""
        SELECT v.name, v.id,
            COUNT(DISTINCT s.id) as sale_count,
            COALESCE(SUM(si.line_total), 0) as gross_sales,
            COALESCE(SUM(si.consignment_amount), 0) as total_consignment,
            COALESCE(SUM(si.line_total - COALESCE(si.consignment_amount, 0)), 0) as net_vendor_credit
        FROM vendors v
        LEFT JOIN sale_items si ON si.vendor_id = v.id
        LEFT JOIN sales s ON s.id = si.sale_id AND s.is_voided = false
        WHERE v.role = 'vendor'
        GROUP BY v.id, v.name
        ORDER BY v.name
    """))
    result["all_time_sales"] = [
        {
            "name": r.name, "sale_count": r.sale_count,
            "gross_sales": float(r.gross_sales),
            "total_consignment": float(r.total_consignment),
            "net_vendor_credit": float(r.net_vendor_credit),
        }
        for r in sales.fetchall()
    ]

    # 3. Current month sales
    month = await db.execute(text("""
        SELECT v.name,
            COUNT(DISTINCT s.id) as sale_count,
            COALESCE(SUM(si.line_total), 0) as gross_sales,
            COALESCE(SUM(si.line_total - COALESCE(si.consignment_amount, 0)), 0) as net_vendor_credit
        FROM vendors v
        LEFT JOIN sale_items si ON si.vendor_id = v.id
        LEFT JOIN sales s ON s.id = si.sale_id AND s.is_voided = false
            AND s.created_at >= DATE_TRUNC('month', CURRENT_DATE)
            AND s.created_at < DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
        WHERE v.role = 'vendor'
        GROUP BY v.name
        ORDER BY net_vendor_credit DESC
    """))
    result["current_month_sales"] = [
        {
            "name": r.name, "sale_count": r.sale_count,
            "gross_sales": float(r.gross_sales),
            "net_vendor_credit": float(r.net_vendor_credit),
        }
        for r in month.fetchall()
        if float(r.net_vendor_credit) > 0 or float(r.gross_sales) > 0
    ]

    # 4. Voided sales
    voids = await db.execute(text("""
        SELECT s.id, s.total, s.created_at, s.is_voided, s.voided_at,
               COALESCE(v.name, 'unknown') as cashier_name,
               (SELECT STRING_AGG(v2.name, ', ')
                FROM sale_items si2 JOIN vendors v2 ON v2.id = si2.vendor_id
                WHERE si2.sale_id = s.id) as vendor_names
        FROM sales s
        LEFT JOIN vendors v ON v.id = s.cashier_id
        WHERE s.is_voided = true
        ORDER BY s.created_at DESC
    """))
    result["voided_sales"] = [
        {
            "sale_id": r.id, "total": float(r.total),
            "cashier": r.cashier_name, "vendors": r.vendor_names,
            "created_at": str(r.created_at), "voided_at": str(r.voided_at),
        }
        for r in voids.fetchall()
    ]

    # 5. Payouts
    payouts = await db.execute(text("""
        SELECT v.name, p.period_month, p.gross_sales, p.rent_deducted, p.net_payout, p.status, p.created_at
        FROM payouts p
        JOIN vendors v ON v.id = p.vendor_id
        ORDER BY p.created_at DESC
        LIMIT 50
    """))
    result["payouts"] = [
        {
            "name": r.name, "period": str(r.period_month),
            "gross_sales": float(r.gross_sales), "rent_deducted": float(r.rent_deducted),
            "net_payout": float(r.net_payout), "status": r.status,
            "created_at": str(r.created_at),
        }
        for r in payouts.fetchall()
    ]

    # 6. Balance adjustments
    adj = await db.execute(text("""
        SELECT v.name as vendor_name, a.adjustment_type, a.amount, a.reason,
               a.balance_before, a.balance_after, a.created_at,
               adj.name as adjusted_by_name
        FROM balance_adjustments a
        JOIN vendors v ON v.id = a.vendor_id
        JOIN vendors adj ON adj.id = a.adjusted_by
        ORDER BY a.created_at DESC
    """))
    result["balance_adjustments"] = [
        {
            "vendor": r.vendor_name, "type": r.adjustment_type,
            "amount": float(r.amount), "reason": r.reason,
            "before": float(r.balance_before), "after": float(r.balance_after),
            "by": r.adjusted_by_name, "at": str(r.created_at),
        }
        for r in adj.fetchall()
    ]

    # 7. Discrepancy check
    disc = await db.execute(text("""
        WITH vendor_credits AS (
            SELECT si.vendor_id,
                COALESCE(SUM(si.line_total - COALESCE(si.consignment_amount, 0)), 0) as total_credit
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id AND s.is_voided = false
            GROUP BY si.vendor_id
        ),
        vendor_debits AS (
            SELECT si.vendor_id,
                COALESCE(SUM(si.line_total - COALESCE(si.consignment_amount, 0)), 0) as total_debit
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id AND s.is_voided = true
            GROUP BY si.vendor_id
        ),
        payout_totals AS (
            SELECT vendor_id, COALESCE(SUM(net_payout), 0) as total_payout
            FROM payouts WHERE status != 'cancelled'
            GROUP BY vendor_id
        ),
        adjustment_totals AS (
            SELECT vendor_id,
                COALESCE(SUM(CASE WHEN adjustment_type='credit' THEN amount ELSE -amount END), 0) as net_adj
            FROM balance_adjustments
            GROUP BY vendor_id
        )
        SELECT v.name,
            COALESCE(vb.balance, 0) as stored_balance,
            COALESCE(vc.total_credit, 0) as total_credits,
            COALESCE(vd.total_debit, 0) as total_debits,
            COALESCE(pt.total_payout, 0) as total_payouts,
            COALESCE(at.net_adj, 0) as net_adjustments,
            COALESCE(vc.total_credit, 0) - COALESCE(vd.total_debit, 0)
                - COALESCE(pt.total_payout, 0) + COALESCE(at.net_adj, 0) as expected_balance,
            COALESCE(vb.balance, 0) - (
                COALESCE(vc.total_credit, 0) - COALESCE(vd.total_debit, 0)
                - COALESCE(pt.total_payout, 0) + COALESCE(at.net_adj, 0)
            ) as discrepancy
        FROM vendors v
        LEFT JOIN vendor_balances vb ON vb.vendor_id = v.id
        LEFT JOIN vendor_credits vc ON vc.vendor_id = v.id
        LEFT JOIN vendor_debits vd ON vd.vendor_id = v.id
        LEFT JOIN payout_totals pt ON pt.vendor_id = v.id
        LEFT JOIN adjustment_totals at ON at.vendor_id = v.id
        WHERE v.role = 'vendor'
          AND (COALESCE(vc.total_credit, 0) > 0 OR COALESCE(vb.balance, 0) != 0)
    """))
    result["discrepancies"] = [
        {
            "name": r.name,
            "stored_balance": float(r.stored_balance),
            "total_credits": float(r.total_credits),
            "total_debits": float(r.total_debits),
            "total_payouts": float(r.total_payouts),
            "net_adjustments": float(r.net_adjustments),
            "expected_balance": float(r.expected_balance),
            "discrepancy": float(r.discrepancy),
        }
        for r in disc.fetchall()
    ]

    # 8. Non-zero rates
    rates = await db.execute(text("""
        SELECT name, commission_rate, consignment_rate
        FROM vendors WHERE commission_rate != 0 OR consignment_rate != 0
    """))
    result["non_zero_rates"] = [
        {"name": r.name, "commission_rate": float(r.commission_rate), "consignment_rate": float(r.consignment_rate)}
        for r in rates.fetchall()
    ]

    # 9. Negative balances
    neg = await db.execute(text("""
        SELECT v.name, vb.balance, vb.rent_balance
        FROM vendors v
        JOIN vendor_balances vb ON vb.vendor_id = v.id
        WHERE v.role = 'vendor' AND (vb.balance < 0 OR vb.rent_balance < 0)
    """))
    result["negative_balances"] = [
        {"name": r.name, "balance": float(r.balance), "rent_balance": float(r.rent_balance)}
        for r in neg.fetchall()
    ]

    return result
