import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.database import get_db
from app.models.accounting import Account, JournalEntry, JournalLine, Expense, ExpenseReceipt
from app.models.vendor import VendorBalance
from app.models.sale import Sale, SaleItem
from app.routers.auth import get_current_user, require_admin, require_cashier_or_admin
from app.services.spaces import upload_fileobj, spaces_enabled

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting"])


# ── Pydantic schemas ─────────────────────────────────────────────

class AccountCreate(BaseModel):
    number: int
    name: str
    account_type: str
    parent_id: Optional[int] = None
    description: Optional[str] = None


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class JournalLineSchema(BaseModel):
    account_id: int
    debit: float = 0.0
    credit: float = 0.0
    description: Optional[str] = None


class ManualJournalEntry(BaseModel):
    date: date
    description: str
    lines: List[JournalLineSchema]


class ExpenseCreate(BaseModel):
    date: date
    amount: float
    account_id: int
    payee: Optional[str] = None
    description: str
    payment_method: Optional[str] = None
    tax_deductible: bool = True


class ExpenseUpdate(BaseModel):
    date: Optional[date] = None
    amount: Optional[float] = None
    account_id: Optional[int] = None
    payee: Optional[str] = None
    description: Optional[str] = None
    payment_method: Optional[str] = None
    tax_deductible: Optional[bool] = None


# ── Validation ──────────────────────────────────────────────────

VALID_ACCOUNT_TYPES = {"asset", "liability", "equity", "income", "cogs", "expense"}
EXPENSE_TYPES = {"expense", "cogs"}

ACCOUNT_NUMBER_NAMES = {
    "1000-1099": "Cash accounts",
    "1100-1199": "Accounts Receivable",
    "1200-1299": "Inventory",
    "2000-2099": "Accounts Payable",
    "2200-2299": "Sales Tax Payable",
    "2300-2399": "Gift Card Liability",
    "3000-3099": "Owner's Equity",
    "4000-4099": "Sales Revenue",
    "5000-5099": "Cost of Goods Sold",
    "6000-6099": "Rent & Utilities",
    "6100-6199": "Payroll & Labor",
    "6200-6299": "Supplies & Materials",
    "6300-6399": "Marketing & Advertising",
    "6400-6499": "Insurance",
    "6500-6599": "Professional Services",
    "6600-6699": "Bank & Processing Fees",
    "6700-6799": "Repairs & Maintenance",
    "6900-6999": "Other Expenses",
}


async def _ensure_expense_account(db: AsyncSession, account_id: int) -> Account:
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    if account.account_type not in EXPENSE_TYPES:
        raise HTTPException(400, f"Account {account.number} is not an expense account (type: {account.account_type})")
    return account


async def _create_journal(entry_date: date, description: str, reference_type: str,
                          reference_id: Optional[int], created_by: Optional[int],
                          db: AsyncSession,
                          *pairs):
    if not pairs:
        return None
    entry = JournalEntry(date=entry_date, description=description,
                         reference_type=reference_type, reference_id=reference_id,
                         created_by=created_by)
    for account_id, debit, credit, line_desc in pairs:
        line = JournalLine(account_id=account_id, debit=Decimal(str(debit or 0)),
                           credit=Decimal(str(credit or 0)), description=line_desc)
        entry.lines.append(line)
    total_debit = sum(l.debit for l in entry.lines)
    total_credit = sum(l.credit for l in entry.lines)
    if abs(total_debit - total_credit) > Decimal("0.01"):
        raise HTTPException(400, f"Journal not balanced: debits={total_debit}, credits={total_credit}")
    db.add(entry)
    return entry


# ── CHART OF ACCOUNTS ────────────────────────────────────────────

@router.get("/accounts")
async def list_accounts(db: AsyncSession = Depends(get_db),
                        _=Depends(require_cashier_or_admin)):
    result = await db.execute(
        select(Account).order_by(Account.number)
    )
    accounts = result.scalars().all()
    return {
        "accounts": [
            {
                "id": a.id, "number": a.number, "name": a.name,
                "account_type": a.account_type, "parent_id": a.parent_id,
                "is_active": a.is_active, "is_system": a.is_system,
                "description": a.description,
            }
            for a in accounts
        ],
        "categories": [
            {"range": k, "label": v} for k, v in ACCOUNT_NUMBER_NAMES.items()
        ],
    }


@router.post("/accounts")
async def create_account(body: AccountCreate, db: AsyncSession = Depends(get_db),
                         _=Depends(require_admin)):
    if body.account_type not in VALID_ACCOUNT_TYPES:
        raise HTTPException(400, f"Invalid type: {body.account_type}")
    existing = await db.execute(
        select(Account).where(Account.number == body.number)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Account number {body.number} already exists")
    account = Account(**body.model_dump())
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return {"id": account.id, "number": account.number, "name": account.name}


@router.put("/accounts/{account_id}")
async def update_account(account_id: int, body: AccountUpdate,
                         db: AsyncSession = Depends(get_db),
                         _=Depends(require_admin)):
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    if account.is_system:
        raise HTTPException(400, "System accounts cannot be edited")
    if body.account_type and body.account_type not in VALID_ACCOUNT_TYPES:
        raise HTTPException(400, f"Invalid type: {body.account_type}")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(account, key, val)
    await db.commit()
    return {"id": account.id, "name": account.name, "is_active": account.is_active}


@router.delete("/accounts/{account_id}")
async def deactivate_account(account_id: int, db: AsyncSession = Depends(get_db),
                             _=Depends(require_admin)):
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    if account.is_system:
        raise HTTPException(400, "System accounts cannot be deleted")
    account.is_active = False
    await db.commit()
    return {"ok": True}


# ── EXPENSES ─────────────────────────────────────────────────────

@router.get("/expenses")
async def list_expenses(start_date: Optional[str] = Query(None),
                        end_date: Optional[str] = Query(None),
                        account_id: Optional[int] = Query(None),
                        payee: Optional[str] = Query(None),
                        limit: int = Query(50, ge=1, le=500),
                        offset: int = Query(0, ge=0),
                        db: AsyncSession = Depends(get_db),
                        _=Depends(require_cashier_or_admin)):
    query = select(Expense).options(
        selectinload(Expense.account),
        selectinload(Expense.receipts),
    )
    filters = []
    if start_date:
        filters.append(Expense.date >= date.fromisoformat(start_date))
    if end_date:
        filters.append(Expense.date <= date.fromisoformat(end_date))
    if account_id:
        filters.append(Expense.account_id == account_id)
    if payee:
        filters.append(Expense.payee.ilike(f"%{payee}%"))
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(Expense.date.desc(), Expense.id.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    expenses = result.scalars().all()

    count_q = select(func.count(Expense.id))
    if filters:
        count_q = count_q.where(and_(*filters))
    total = (await db.execute(count_q)).scalar()

    return {
        "expenses": [
            {
                "id": e.id, "date": e.date.isoformat(), "amount": float(e.amount),
                "account_id": e.account_id,
                "account_name": e.account.name if e.account else "",
                "payee": e.payee, "description": e.description,
                "payment_method": e.payment_method,
                "tax_deductible": e.tax_deductible,
                "receipt_count": len(e.receipts),
                "receipt_urls": [r.file_url for r in e.receipts],
            }
            for e in expenses
        ],
        "total": total,
    }


@router.post("/expenses")
async def create_expense(body: ExpenseCreate, db: AsyncSession = Depends(get_db),
                         current_user=Depends(get_current_user),
                         _=Depends(require_cashier_or_admin)):
    await _ensure_expense_account(db, body.account_id)

    account = await db.get(Account, body.account_id)

    cash_account_id = await _get_expense_payment_account(db, body.payment_method)

    entry = await _create_journal(
        entry_date=body.date,
        description=f"Expense: {body.description}",
        reference_type="expense",
        reference_id=None,
        created_by=current_user.id,
        db=db,
        (body.account_id, body.amount, 0, body.description),
        (cash_account_id, 0, body.amount,
           body.payee or "Cash/AP"),
    )

    expense = Expense(
        date=body.date, amount=Decimal(str(body.amount)),
        account_id=body.account_id, payee=body.payee,
        description=body.description, payment_method=body.payment_method,
        tax_deductible=body.tax_deductible,
        journal_entry_id=entry.id if entry else None,
        created_by=current_user.id,
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)

    if entry:
        entry.reference_id = expense.id
        await db.commit()

    return {"id": expense.id, "date": expense.date.isoformat(),
            "amount": float(expense.amount), "description": expense.description}


@router.get("/expenses/{expense_id}")
async def get_expense(expense_id: int, db: AsyncSession = Depends(get_db),
                      _=Depends(require_cashier_or_admin)):
    result = await db.execute(
        select(Expense).options(
            selectinload(Expense.account),
            selectinload(Expense.receipts),
            selectinload(Expense.journal_entry).selectinload(JournalEntry.lines),
        ).where(Expense.id == expense_id)
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(404, "Expense not found")
    return {
        "id": expense.id, "date": expense.date.isoformat(),
        "amount": float(expense.amount),
        "account_id": expense.account_id,
        "account_name": expense.account.name if expense.account else "",
        "payee": expense.payee, "description": expense.description,
        "payment_method": expense.payment_method,
        "tax_deductible": expense.tax_deductible,
        "receipts": [{"id": r.id, "file_url": r.file_url, "filename": r.filename}
                     for r in expense.receipts],
        "journal_entry_id": expense.journal_entry_id,
    }


@router.put("/expenses/{expense_id}")
async def update_expense(expense_id: int, body: ExpenseUpdate,
                         db: AsyncSession = Depends(get_db),
                         _=Depends(require_admin)):
    expense = await db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(404, "Expense not found")
    for key, val in body.model_dump(exclude_unset=True).items():
        if val is not None:
            if key == "amount":
                val = Decimal(str(val))
            setattr(expense, key, val)
    await db.commit()
    return {"id": expense.id, "amount": float(expense.amount)}


@router.delete("/expenses/{expense_id}")
async def void_expense(expense_id: int, db: AsyncSession = Depends(get_db),
                       _=Depends(require_admin)):
    expense = await db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(404, "Expense not found")
    if expense.journal_entry_id:
        reverse_entry = JournalEntry(
            date=date.today(),
            description=f"Void expense #{expense.id}: {expense.description}",
            reference_type="expense_void",
            reference_id=expense.id,
        )
        original_entry = await db.get(JournalEntry, expense.journal_entry_id)
        if original_entry:
            for line in original_entry.lines:
                JournalLine(
                    entry=reverse_entry,
                    account_id=line.account_id,
                    debit=line.credit,
                    credit=line.debit,
                    description=f"Reversal: {line.description or ''}"
                )
        db.add(reverse_entry)
    await db.delete(expense)
    await db.commit()
    return {"ok": True}


@router.post("/expenses/{expense_id}/receipts")
async def upload_expense_receipt(expense_id: int, file: UploadFile = File(...),
                                 db: AsyncSession = Depends(get_db),
                                 _=Depends(require_cashier_or_admin)):
    expense = await db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(404, "Expense not found")
    filename = file.filename or "receipt.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    content_type = f"image/{ext}" if ext in ("jpg", "jpeg", "png", "gif", "webp") else "application/pdf"
    key = f"receipts/{expense_id}_{uuid.uuid4().hex[:8]}.{ext}"
    file_bytes = await file.read()
    url = None
    if spaces_enabled():
        from app.services.spaces import upload_bytes
        url = upload_bytes(file_bytes, key, content_type)
    if not url:
        raise HTTPException(500, "Failed to upload receipt")
    receipt = ExpenseReceipt(expense_id=expense_id, file_url=url, filename=filename)
    db.add(receipt)
    await db.commit()
    return {"id": receipt.id, "file_url": receipt.file_url, "filename": receipt.filename}


# ── JOURNAL ──────────────────────────────────────────────────────

@router.get("/journal")
async def list_journal(start_date: Optional[str] = Query(None),
                       end_date: Optional[str] = Query(None),
                       account_id: Optional[int] = Query(None),
                       limit: int = Query(50, ge=1, le=500),
                       offset: int = Query(0, ge=0),
                       db: AsyncSession = Depends(get_db),
                       _=Depends(require_cashier_or_admin)):
    if account_id:
        line_q = select(JournalLine.entry_id).where(JournalLine.account_id == account_id)
        line_result = await db.execute(line_q)
        entry_ids = [r[0] for r in line_result.all()]
        if not entry_ids:
            return {"entries": [], "total": 0}
        query = select(JournalEntry).options(
            selectinload(JournalEntry.lines).selectinload(JournalLine.account)
        ).where(JournalEntry.id.in_(entry_ids))
    else:
        query = select(JournalEntry).options(
            selectinload(JournalEntry.lines).selectinload(JournalLine.account)
        )
    filters = []
    if start_date:
        filters.append(JournalEntry.date >= date.fromisoformat(start_date))
    if end_date:
        filters.append(JournalEntry.date <= date.fromisoformat(end_date))
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(JournalEntry.date.desc(), JournalEntry.id.desc())
    count_q = select(func.count()).select_from(query.subquery()) if filters else select(func.count()).select_from(JournalEntry.__table__)
    total = (await db.execute(count_q)).scalar()
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    entries = result.scalars().all()
    return {
        "entries": [
            {
                "id": e.id, "date": e.date.isoformat(), "description": e.description,
                "reference_type": e.reference_type, "reference_id": e.reference_id,
                "lines": [
                    {"account_id": l.account_id, "account_name": l.account.name if l.account else "",
                     "account_number": l.account.number if l.account else 0,
                     "debit": float(l.debit), "credit": float(l.credit),
                     "description": l.description}
                    for l in e.lines
                ],
            }
            for e in entries
        ],
        "total": total,
    }


@router.get("/journal/{entry_id}")
async def get_journal_entry(entry_id: int, db: AsyncSession = Depends(get_db),
                            _=Depends(require_cashier_or_admin)):
    result = await db.execute(
        select(JournalEntry).options(
            selectinload(JournalEntry.lines).selectinload(JournalLine.account)
        ).where(JournalEntry.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Journal entry not found")
    return {
        "id": entry.id, "date": entry.date.isoformat(), "description": entry.description,
        "reference_type": entry.reference_type, "reference_id": entry.reference_id,
        "lines": [
            {"account_id": l.account_id, "account_name": l.account.name if l.account else "",
             "account_number": l.account.number if l.account else 0,
             "debit": float(l.debit), "credit": float(l.credit),
             "description": l.description}
            for l in entry.lines
        ],
    }


@router.post("/journal")
async def create_manual_journal(body: ManualJournalEntry,
                                db: AsyncSession = Depends(get_db),
                                current_user=Depends(get_current_user),
                                _=Depends(require_admin)):
    pairs = [(line.account_id, line.debit, line.credit, line.description)
             for line in body.lines]
    entry = await _create_journal(body.date, body.description, "manual", None,
                                  current_user.id, db, *pairs)
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "description": entry.description}


# ── REPORTS ──────────────────────────────────────────────────────

async def _get_account_balances(db: AsyncSession, as_of: Optional[date] = None):
    """Get the balance for each account from journal lines up to as_of date."""
    line_query = select(
        JournalLine.account_id,
        func.sum(JournalLine.debit).label("total_debit"),
        func.sum(JournalLine.credit).label("total_credit"),
    ).join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
    if as_of:
        line_query = line_query.where(JournalEntry.date <= as_of)
    line_query = line_query.group_by(JournalLine.account_id)
    result = await db.execute(line_query)
    account_balances = {}
    for row in result:
        account_balances[row.account_id] = {
            "debit": float(row.total_debit or 0),
            "credit": float(row.total_credit or 0),
        }
    accounts_result = await db.execute(
        select(Account).where(Account.is_active == True)
    )
    accounts = accounts_result.scalars().all()
    return accounts, account_balances


def _balance_for_type(account_type: str, debit: float, credit: float) -> float:
    """Calculate balance from debit/credit based on account type."""
    if account_type in ("asset", "cogs", "expense"):
        return debit - credit
    else:
        return credit - debit


@router.get("/reports/pl")
async def profit_and_loss(start_date: str = Query(...),
                          end_date: str = Query(...),
                          db: AsyncSession = Depends(get_db),
                          _=Depends(require_cashier_or_admin)):
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    line_query = select(
        JournalLine.account_id,
        func.sum(JournalLine.debit).label("total_debit"),
        func.sum(JournalLine.credit).label("total_credit"),
    ).join(JournalEntry, JournalLine.entry_id == JournalEntry.id).where(
        and_(JournalEntry.date >= start, JournalEntry.date <= end)
    ).group_by(JournalLine.account_id)
    result = await db.execute(line_query)
    raw_balances = {}
    for row in result:
        raw_balances[row.account_id] = {
            "debit": float(row.total_debit or 0),
            "credit": float(row.total_credit or 0),
        }
    accounts_result = await db.execute(
        select(Account).where(Account.is_active == True).order_by(Account.number)
    )
    accounts = accounts_result.scalars().all()

    income_items = []
    cogs_items = []
    expense_items = []
    total_income = 0.0
    total_cogs = 0.0
    total_expenses = 0.0

    for a in accounts:
        b = raw_balances.get(a.id, {"debit": 0.0, "credit": 0.0})
        if a.account_type == "income":
            bal = _balance_for_type(a.account_type, b["debit"], b["credit"])
            if abs(bal) > 0.01:
                income_items.append({"account": a.name, "number": a.number, "amount": round(bal, 2)})
                total_income += bal
        elif a.account_type == "cogs":
            bal = _balance_for_type(a.account_type, b["debit"], b["credit"])
            if abs(bal) > 0.01:
                cogs_items.append({"account": a.name, "number": a.number, "amount": round(bal, 2)})
                total_cogs += bal
        elif a.account_type == "expense":
            bal = _balance_for_type(a.account_type, b["debit"], b["credit"])
            if abs(bal) > 0.01:
                expense_items.append({"account": a.name, "number": a.number, "amount": round(bal, 2)})
                total_expenses += bal

    total_income = round(total_income, 2)
    total_cogs = round(total_cogs, 2)
    total_expenses = round(total_expenses, 2)
    gross_profit = round(total_income - total_cogs, 2)
    net_profit = round(gross_profit - total_expenses, 2)

    return {
        "period": {"start": start_date, "end": end_date},
        "income": {"items": income_items, "total": total_income},
        "cogs": {"items": cogs_items, "total": total_cogs},
        "gross_profit": gross_profit,
        "expenses": {"items": expense_items, "total": total_expenses},
        "net_profit": net_profit,
        "margin_pct": round((net_profit / total_income * 100) if total_income > 0 else 0, 1),
    }


@router.get("/reports/balance-sheet")
async def balance_sheet(as_of: str = Query(...),
                        db: AsyncSession = Depends(get_db),
                        _=Depends(require_cashier_or_admin)):
    end = date.fromisoformat(as_of)
    accounts, balances = await _get_account_balances(db, as_of=end)

    assets = []
    liabilities = []
    equity = []
    total_assets = 0.0
    total_liabilities = 0.0
    total_equity = 0.0

    for a in accounts:
        b = balances.get(a.id, {"debit": 0.0, "credit": 0.0})
        bal = round(_balance_for_type(a.account_type, b["debit"], b["credit"]), 2)
        if abs(bal) < 0.01:
            continue
        item = {"account": a.name, "number": a.number, "amount": bal}
        if a.account_type == "asset":
            assets.append(item)
            total_assets += bal
        elif a.account_type == "liability":
            liabilities.append(item)
            total_liabilities += bal
        elif a.account_type == "equity":
            equity.append(item)
            total_equity += bal

    total_assets = round(total_assets, 2)
    total_liabilities = round(total_liabilities, 2)
    total_equity = round(total_equity, 2)

    return {
        "as_of": as_of,
        "assets": {"items": assets, "total": total_assets},
        "liabilities": {"items": liabilities, "total": total_liabilities},
        "equity": {"items": equity, "total": total_equity},
        "liabilities_equity_total": round(total_liabilities + total_equity, 2),
    }


@router.get("/reports/trial-balance")
async def trial_balance(as_of: str = Query(...),
                        db: AsyncSession = Depends(get_db),
                        _=Depends(require_cashier_or_admin)):
    end = date.fromisoformat(as_of)
    accounts, balances = await _get_account_balances(db, as_of=end)

    items = []
    total_debit = 0.0
    total_credit = 0.0

    for a in accounts:
        b = balances.get(a.id, {"debit": 0.0, "credit": 0.0})
        d = round(b["debit"], 2)
        c = round(b["credit"], 2)
        net = round(_balance_for_type(a.account_type, d, c), 2)
        if abs(d) < 0.01 and abs(c) < 0.01:
            continue
        items.append({
            "account": a.name, "number": a.number, "type": a.account_type,
            "debit": d, "credit": c, "net_balance": net,
        })
        total_debit += d
        total_credit += c

    return {
        "as_of": as_of,
        "items": items,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
    }


@router.get("/reports/tax-summary")
async def tax_summary(year: int = Query(...), quarter: Optional[int] = Query(None),
                      db: AsyncSession = Depends(get_db),
                      _=Depends(require_cashier_or_admin)):
    if quarter:
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        end_month = start_month + 2
        end = date(year, end_month, 28)
    else:
        start = date(year, 1, 1)
        end = date(year, 12, 31)

    total_sales = 0.0
    total_tax = 0.0
    sales_result = await db.execute(
        select(func.coalesce(func.sum(Sale.total), 0), func.coalesce(func.sum(Sale.tax_total), 0))
        .where(and_(Sale.created_at >= start, Sale.created_at <= end, Sale.voided == False))
    )
    row = sales_result.one_or_none()
    if row:
        total_sales = float(row[0] or 0)
        total_tax = float(row[1] or 0)

    total_deductible = 0.0
    expense_result = await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(and_(Expense.date >= start, Expense.date <= end, Expense.tax_deductible == True))
    )
    deductible = expense_result.scalar()
    if deductible:
        total_deductible = float(deductible)

    return {
        "period": {"year": year, "quarter": quarter, "start": start.isoformat(), "end": end.isoformat()},
        "sales": round(total_sales, 2),
        "sales_tax_collected": round(total_tax, 2),
        "deductible_expenses": round(total_deductible, 2),
        "notes": "Sales tax collected and deductible expenses for your accountant. Actual taxable income requires accountant review.",
    }


@router.get("/reports/expenses-by-category")
async def expenses_by_category(start_date: str = Query(...),
                               end_date: str = Query(...),
                               db: AsyncSession = Depends(get_db),
                               _=Depends(require_cashier_or_admin)):
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    result = await db.execute(
        select(Expense.account_id, func.sum(Expense.amount).label("total"))
        .where(and_(Expense.date >= start, Expense.date <= end))
        .group_by(Expense.account_id)
        .order_by(func.sum(Expense.amount).desc())
    )
    categories = []
    for row in result:
        account = await db.get(Account, row.account_id)
        categories.append({
            "account_id": row.account_id,
            "account_name": account.name if account else "Unknown",
            "total": round(float(row.total or 0), 2),
        })
    return {"period": {"start": start_date, "end": end_date}, "categories": categories}


# ── UTILITY ──────────────────────────────────────────────────────

async def _get_expense_payment_account(db: AsyncSession, method: Optional[str]) -> int:
    """Return the default cash account for expense credit entry."""
    result = await db.execute(
        select(Account).where(Account.number == 1000, Account.is_active == True)
    )
    account = result.scalar_one_or_none()
    if account:
        return account.id
    result = await db.execute(
        select(Account).where(Account.account_type == "asset", Account.is_active == True).limit(1)
    )
    account = result.scalar_one_or_none()
    if account:
        return account.id
    raise HTTPException(400, "No cash/asset account found in chart of accounts")
