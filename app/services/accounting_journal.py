"""
Auto-journal helpers — create double-entry journal entries for
standard business events (sales, rent payments, payouts, gift cards).
"""
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import Account, JournalEntry, JournalLine

logger = logging.getLogger(__name__)


def _d(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)


async def _get_account_by_number(db: AsyncSession, number: int) -> Optional[Account]:
    result = await db.execute(
        select(Account).where(Account.number == number, Account.is_active == True)
    )
    # Use first() instead of scalar_one_or_none() to gracefully handle duplicates
    return result.scalars().first()


async def _ensure_account(db: AsyncSession, number: int, name: str, account_type: str) -> Account:
    """Get or create a system account by number."""
    account = await _get_account_by_number(db, number)
    if not account:
        account = Account(
            number=number, name=name, account_type=account_type,
            is_system=True, is_active=True,
        )
        db.add(account)
        await db.flush()
    return account


async def _create_entry(
    db: AsyncSession,
    entry_date: date,
    description: str,
    reference_type: str,
    reference_id: Optional[int],
    created_by: Optional[int],
    *pairs,
) -> JournalEntry:
    """pairs = (account_number, debit, credit, line_description)"""
    entry = JournalEntry(
        date=entry_date, description=description,
        reference_type=reference_type, reference_id=reference_id,
        created_by=created_by,
    )
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for acct_num, debit, credit, line_desc in pairs:
        account = await _ensure_account(
            db, acct_num,
            f"Account {acct_num}", "asset",
        )
        d = _d(debit)
        c = _d(credit)
        if d > 0 or c > 0:
            line = JournalLine(
                account_id=account.id, debit=d, credit=c, description=line_desc,
            )
            entry.lines.append(line)
            total_debit += d
            total_credit += c

    if abs(total_debit - total_credit) > Decimal("0.02"):
        logger.warning(
            "Journal not perfectly balanced for %s: debits=%.2f credits=%.2f",
            description, total_debit, total_credit,
        )

    db.add(entry)
    return entry


async def journal_sale(
    db: AsyncSession,
    sale_id: int,
    sale_date: date,
    subtotal: Decimal,
    tax_amount: Decimal,
    total: Decimal,
    payment_method: str,
    gift_card_amount: Optional[Decimal],
    created_by: Optional[int],
) -> Optional[JournalEntry]:
    """Record a completed sale in the journal.

    Standard sale (cash/card/crypto):
        Debit  Cash/Receivable (1000)    $total
        Credit Sales Revenue (4000)       $subtotal
        Credit Sales Tax Payable (2200)   $tax

    Gift card sale:
        Debit  Gift Card Liability (2300) $total
        Credit Sales Revenue (4000)       $subtotal
        Credit Sales Tax Payable (2200)   $tax

    Split (gift card + cash):
        Debit  Gift Card Liability (2300) $gc_amount
        Debit  Cash/Receivable (1000)     $total - $gc_amount
        Credit Sales Revenue (4000)       $subtotal
        Credit Sales Tax Payable (2200)   $tax
    """
    gc = _d(gift_card_amount) if gift_card_amount else Decimal("0")
    cash_portion = _d(total) - gc

    pairs = []
    if payment_method == "gift_card":
        pairs.append((2300, _d(total), Decimal("0"), f"Gift card redeemed — Sale #{sale_id}"))
    elif payment_method == "split" and gc > 0:
        if gc > 0:
            pairs.append((2300, gc, Decimal("0"), f"Gift card portion — Sale #{sale_id}"))
        if cash_portion > 0:
            pairs.append((1000, cash_portion, Decimal("0"), f"Cash/card portion — Sale #{sale_id}"))
    else:
        pairs.append((1000, _d(total), Decimal("0"), f"Revenue — Sale #{sale_id}"))

    pairs.append((4000, Decimal("0"), _d(subtotal), f"Sales revenue — Sale #{sale_id}"))
    if _d(tax_amount) > 0:
        pairs.append((2200, Decimal("0"), _d(tax_amount), f"Sales tax collected — Sale #{sale_id}"))

    return await _create_entry(
        db, sale_date,
        f"Sale #{sale_id} ({payment_method})",
        "sale", sale_id, created_by,
        *pairs,
    )


async def journal_rent_payment(
    db: AsyncSession,
    payment_id: int,
    payment_date: date,
    amount: Decimal,
    method: str,
    created_by: Optional[int],
) -> Optional[JournalEntry]:
    """Record a rent payment received in the journal.

        Debit  Cash/Receivable (1000)    $amount
        Credit Rent Income (not sales — use 6900 as misc contra or custom)
            Actually rent from vendors is a reduction of what we owe them,
            not really income. For simplicity we debit cash and credit a
            vendor payable contra. Use a dedicated rent account if one exists.

    For now, record as:
        Debit  Cash (1000)        $amount
        Credit Rent Collected — contra to vendor payable
    """
    return await _create_entry(
        db, payment_date,
        f"Rent payment #{payment_id} ({method})",
        "rent_payment", payment_id, created_by,
        (1000, _d(amount), Decimal("0"), f"Rent received — Payment #{payment_id}"),
        (6900, Decimal("0"), _d(amount), f"Rent collected — Payment #{payment_id}"),
    )


async def journal_payout(
    db: AsyncSession,
    payout_id: int,
    payout_date: date,
    gross_sales: Decimal,
    rent_deducted: Decimal,
    net_payout: Decimal,
    created_by: Optional[int],
) -> Optional[JournalEntry]:
    """Record a vendor payout in the journal.

        Debit  Vendor Payable / COGS?  $gross_sales
        Credit Cash (1000)              $net_payout
        Credit Rent Collected (6900)    $rent_deducted
    """
    pairs = [
        (2000, _d(gross_sales), Decimal("0"), f"Vendor payable released — Payout #{payout_id}"),
        (1000, Decimal("0"), _d(net_payout), f"Cash paid to vendor — Payout #{payout_id}"),
    ]
    if _d(rent_deducted) > 0:
        pairs.append((6900, Decimal("0"), _d(rent_deducted), f"Rent deducted — Payout #{payout_id}"))

    return await _create_entry(
        db, payout_date,
        f"Vendor payout #{payout_id}",
        "payout", payout_id, created_by,
        *pairs,
    )


async def journal_gift_card_purchase(
    db: AsyncSession,
    gc_id: int,
    purchase_date: date,
    amount: Decimal,
    created_by: Optional[int],
) -> Optional[JournalEntry]:
    """Record a gift card purchase (customer buys a gift card).

        Debit  Cash (1000)              $amount
        Credit Gift Card Liability (2300) $amount
    """
    return await _create_entry(
        db, purchase_date,
        f"Gift card purchased — GC #{gc_id}",
        "gift_card_purchase", gc_id, created_by,
        (1000, _d(amount), Decimal("0"), f"Cash received — GC #{gc_id}"),
        (2300, Decimal("0"), _d(amount), f"Liability created — GC #{gc_id}"),
    )


async def journal_gift_card_load(
    db: AsyncSession,
    gc_id: int,
    load_date: date,
    amount: Decimal,
    created_by: Optional[int],
) -> Optional[JournalEntry]:
    """Record loading money onto an existing gift card.

        Debit  Cash (1000)              $amount
        Credit Gift Card Liability (2300) $amount
    """
    return await _create_entry(
        db, load_date,
        f"Gift card reloaded — GC #{gc_id}",
        "gift_card_load", gc_id, created_by,
        (1000, _d(amount), Decimal("0"), f"Cash received — GC #{gc_id}"),
        (2300, Decimal("0"), _d(amount), f"Liability increased — GC #{gc_id}"),
    )
