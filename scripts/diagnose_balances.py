"""
Diagnostic script to analyze vendor balance discrepancies.

Run against production: python scripts/diagnose_balances.py
Or locally with offline DB.

Compares VendorBalance.balance against actual transaction history:
  - sale_items (credits)
  - voided sales (reversals)
  - payouts (debits)
  - balance_adjustments (manual corrections)
"""

import asyncio
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, select, func
from app.database import AsyncSessionLocal, engine
from app.models.vendor import Vendor, VendorBalance
from app.models.sale import Sale, SaleItem
from app.models.payout import Payout
from app.models.vendor import BalanceAdjustment


async def diagnose():
    print("=" * 80)
    print("VENDOR BALANCE DIAGNOSTICS")
    print("=" * 80)
    print()

    async with AsyncSessionLocal() as db:
        # ── 1. All vendors with their current balance ──────────────────────
        print("## 1. CURRENT VENDOR BALANCES\n")
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
        vendor_rows = vendors.fetchall()

        print(f"{'Name':<25} {'Booth':<8} {'Balance':>10} {'RentBal':>10} {'Comm':>6} {'Consign':>8} {'Rent':>8}")
        print("-" * 85)
        for r in vendor_rows:
            print(f"{r.name:<25} {r.booth_number or '':>6}  {float(r.balance):>10.2f} {float(r.rent_balance):>10.2f} {float(r.commission_rate):>5.2f} {float(r.consignment_rate):>7.4f} {float(r.monthly_rent or 0):>8.2f}")
        print()

        # ── 2. Actual sales per vendor (all time, non-voided) ─────────────
        print("## 2. ACTUAL SALES PER VENDOR (non-voided, all time)\n")
        sales_data = await db.execute(text("""
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
        sales_rows = sales_data.fetchall()

        print(f"{'Name':<25} {'Sales#':>6} {'Gross':>10} {'Consign':>10} {'NetCredit':>10}")
        print("-" * 65)
        for r in sales_rows:
            print(f"{r.name:<25} {r.sale_count:>6} {float(r.gross_sales):>10.2f} {float(r.total_consignment):>10.2f} {float(r.net_vendor_credit):>10.2f}")
        print()

        # ── 3. Current month sales ────────────────────────────────────────
        print("## 3. CURRENT MONTH SALES (April 2026)\n")
        month_data = await db.execute(text("""
            SELECT v.name, v.id,
                COUNT(DISTINCT s.id) as sale_count,
                COALESCE(SUM(si.line_total), 0) as gross_sales,
                COALESCE(SUM(si.line_total - COALESCE(si.consignment_amount, 0)), 0) as net_vendor_credit
            FROM vendors v
            LEFT JOIN sale_items si ON si.vendor_id = v.id
            LEFT JOIN sales s ON s.id = si.sale_id AND s.is_voided = false
                AND s.created_at >= DATE_TRUNC('month', CURRENT_DATE)
                AND s.created_at < DATE_TRUNC('month', CURRENT_DATE) + INTERVAL '1 month'
            WHERE v.role = 'vendor'
            GROUP BY v.id, v.name
            ORDER BY net_vendor_credit DESC
        """))
        month_rows = month_data.fetchall()

        print(f"{'Name':<25} {'Sales#':>6} {'Gross':>10} {'NetCredit':>10}")
        print("-" * 55)
        for r in month_rows:
            if float(r.net_vendor_credit) > 0 or float(r.gross_sales) > 0:
                print(f"{r.name:<25} {r.sale_count:>6} {float(r.gross_sales):>10.2f} {float(r.net_vendor_credit):>10.2f}")
        print()

        # ── 4. Voided sales ───────────────────────────────────────────────
        print("## 4. VOIDED SALES\n")
        voids = await db.execute(text("""
            SELECT v.name, s.id as sale_id, s.total, s.created_at, s.is_voided, s.voided_at
            FROM sales s
            JOIN vendors v ON v.id = s.cashier_id
            WHERE s.is_voided = true
            ORDER BY s.created_at DESC
        """))
        void_rows = voids.fetchall()
        if void_rows:
            for r in void_rows:
                print(f"  Sale #{r.sale_id}: ${float(r.total):.2f} by {r.name}, created {r.created_at}, voided {r.voided_at}")
        else:
            print("  No voided sales found.")
        print()

        # ── 5. Payouts ────────────────────────────────────────────────────
        print("## 5. PAYOUTS\n")
        payouts = await db.execute(text("""
            SELECT v.name, p.period_month, p.gross_sales, p.rent_deducted, p.net_payout, p.status, p.created_at
            FROM payouts p
            JOIN vendors v ON v.id = p.vendor_id
            ORDER BY p.created_at DESC
            LIMIT 30
        """))
        payout_rows = payouts.fetchall()
        if payout_rows:
            print(f"{'Name':<25} {'Period':>10} {'Gross':>10} {'Rent':>8} {'Net':>10} {'Status':>10}")
            print("-" * 80)
            for r in payout_rows:
                print(f"{r.name:<25} {str(r.period_month):>10} {float(r.gross_sales):>10.2f} {float(r.rent_deducted):>8.2f} {float(r.net_payout):>10.2f} {r.status:>10}")
        else:
            print("  No payouts found.")
        print()

        # ── 6. Balance adjustments ────────────────────────────────────────
        print("## 6. BALANCE ADJUSTMENTS\n")
        adj = await db.execute(text("""
            SELECT v.name as vendor_name, a.adjustment_type, a.amount, a.reason,
                   a.balance_before, a.balance_after, a.created_at,
                   adj.name as adjusted_by_name
            FROM balance_adjustments a
            JOIN vendors v ON v.id = a.vendor_id
            JOIN vendors adj ON adj.id = a.adjusted_by
            ORDER BY a.created_at DESC
        """))
        adj_rows = adj.fetchall()
        if adj_rows:
            for r in adj_rows:
                print(f"  {r.vendor_name}: {r.adjustment_type} ${float(r.amount):.2f} "
                      f"({float(r.balance_before):.2f} → {float(r.balance_after):.2f}) "
                      f"by {r.adjusted_by_name} — {r.reason}")
        else:
            print("  No balance adjustments found.")
        print()

        # ── 7. Discrepancy check ──────────────────────────────────────────
        print("## 7. DISCREPANCY CHECK: Balance vs. Calculated\n")
        disc = await db.execute(text("""
            WITH vendor_credits AS (
                -- Net vendor credit from non-voided sales
                SELECT si.vendor_id,
                    COALESCE(SUM(si.line_total - COALESCE(si.consignment_amount, 0)), 0) as total_credit
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id AND s.is_voided = false
                GROUP BY si.vendor_id
            ),
            vendor_debits AS (
                -- Voided sales that reversed vendor credit
                SELECT si.vendor_id,
                    COALESCE(SUM(si.line_total - COALESCE(si.consignment_amount, 0)), 0) as total_debit
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id AND s.is_voided = true
                GROUP BY si.vendor_id
            ),
            payout_totals AS (
                -- Total paid out (not cancelled)
                SELECT vendor_id, COALESCE(SUM(net_payout), 0) as total_payout
                FROM payouts
                WHERE status != 'cancelled'
                GROUP BY vendor_id
            ),
            adjustment_totals AS (
                -- Net manual adjustments
                SELECT vendor_id,
                    COALESCE(SUM(CASE WHEN adjustment_type='credit' THEN amount ELSE -amount END), 0) as net_adjustment
                FROM balance_adjustments
                GROUP BY vendor_id
            )
            SELECT v.name, v.id,
                COALESCE(vb.balance, 0) as stored_balance,
                COALESCE(vc.total_credit, 0) as total_credits,
                COALESCE(vd.total_debit, 0) as total_debits,
                COALESCE(pt.total_payout, 0) as total_payouts,
                COALESCE(at.net_adjustment, 0) as net_adjustments,
                COALESCE(vc.total_credit, 0) - COALESCE(vd.total_debit, 0) - COALESCE(pt.total_payout, 0) + COALESCE(at.net_adjustment, 0) as expected_balance,
                COALESCE(vb.balance, 0) - (
                    COALESCE(vc.total_credit, 0) - COALESCE(vd.total_debit, 0)
                    - COALESCE(pt.total_payout, 0) + COALESCE(at.net_adjustment, 0)
                ) as discrepancy
            FROM vendors v
            LEFT JOIN vendor_balances vb ON vb.vendor_id = v.id
            LEFT JOIN vendor_credits vc ON vc.vendor_id = v.id
            LEFT JOIN vendor_debits vd ON vd.vendor_id = v.id
            LEFT JOIN payout_totals pt ON pt.vendor_id = v.id
            LEFT JOIN adjustment_totals at ON at.vendor_id = v.id
            WHERE v.role = 'vendor'
              AND (vc.total_credit > 0 OR vb.balance != 0 OR vb.balance IS NULL)
            ORDER BY ABS(
                COALESCE(vb.balance, 0) - (
                    COALESCE(vc.total_credit, 0) - COALESCE(vd.total_debit, 0)
                    - COALESCE(pt.total_payout, 0) + COALESCE(at.net_adjustment, 0)
                )
            ) DESC
        """))
        disc_rows = disc.fetchall()

        print(f"{'Name':<25} {'Stored':>10} {'Credits':>10} {'Debits':>8} {'Payouts':>10} {'Adj':>8} {'Expected':>10} {'Diff':>10}")
        print("-" * 100)
        has_discrepancy = False
        for r in disc_rows:
            diff = float(r.discrepancy)
            marker = " ⚠️" if abs(diff) > 0.01 else ""
            if abs(diff) > 0.01:
                has_discrepancy = True
            print(f"{r.name:<25} {float(r.stored_balance):>10.2f} {float(r.total_credits):>10.2f} {float(r.total_debits):>8.2f} {float(r.total_payouts):>10.2f} {float(r.net_adjustments):>8.2f} {float(r.expected_balance):>10.2f} {diff:>10.2f}{marker}")

        if not has_discrepancy:
            print("\n  ✅ No discrepancies found. All balances match transaction history.")
        else:
            print(f"\n  ⚠️  Found vendors with balance discrepancies!")
        print()

        # ── 8. Non-zero commission/consignment rates ──────────────────────
        print("## 8. NON-ZERO COMMISSION/CONSIGNMENT RATES\n")
        rates = await db.execute(text("""
            SELECT name, commission_rate, consignment_rate
            FROM vendors
            WHERE commission_rate != 0 OR consignment_rate != 0
        """))
        rate_rows = rates.fetchall()
        if rate_rows:
            for r in rate_rows:
                print(f"  {r.name}: commission={float(r.commission_rate):.4f}, consignment={float(r.consignment_rate):.4f}")
        else:
            print("  All vendors have 0 commission and 0 consignment. ✅")
        print()

        # ── 9. Vendors with negative balances ─────────────────────────────
        print("## 9. VENDORS WITH NEGATIVE BALANCES\n")
        neg = await db.execute(text("""
            SELECT v.name, vb.balance, vb.rent_balance
            FROM vendors v
            JOIN vendor_balances vb ON vb.vendor_id = v.id
            WHERE v.role = 'vendor' AND (vb.balance < 0 OR vb.rent_balance < 0)
        """))
        neg_rows = neg.fetchall()
        if neg_rows:
            for r in neg_rows:
                print(f"  {r.name}: balance={float(r.balance):.2f}, rent_balance={float(r.rent_balance):.2f}")
        else:
            print("  No vendors with negative balances. ✅")
        print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(diagnose())
