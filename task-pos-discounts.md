# Task: Add Discount Feature to POS Checkout

## Overview
Cashiers and admins need to apply discounts at the POS — both per-item discounts (e.g. chipped vase, 20% off) and cart-wide discounts (e.g. loyalty 10% off everything). Discounts can be a flat dollar amount OR a percentage.

## Design notes
- Follow the existing BMM-POS dark editorial style (gold accents, dark surfaces)
- Discounts should be clearly visible in the cart and on receipts
- Both cashiers and admins can apply discounts (no role restriction beyond normal POS access)

---

## PART 1: Backend — Database + API changes

### 1A. Add discount columns to `sale_items` table

File: `app/models/sale.py`

Add to the `SaleItem` class:
```python
discount_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # 'dollar' or 'percent'
discount_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)  # the raw value entered
discount_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)  # calculated $ off
```

### 1B. Add cart-wide discount columns to `sales` table

File: `app/models/sale.py`

Add to the `Sale` class:
```python
discount_type: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # 'dollar' or 'percent'
discount_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
discount_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)  # total $ discount on cart
```

### 1C. Auto-create columns on startup

File: `app/main.py`

Add column-check logic in the lifespan startup (same pattern as existing auto column creation) for:
- `sale_items.discount_type`, `sale_items.discount_value`, `sale_items.discount_amount`
- `sales.discount_type`, `sales.discount_value`, `sales.discount_amount`

### 1D. Update schemas

File: `app/schemas/sale.py`

Update `CartItem`:
```python
class CartItem(BaseModel):
    barcode: str
    quantity: int = 1
    discount_type: Optional[str] = None   # 'dollar' or 'percent'
    discount_value: Optional[float] = None  # e.g. 5.00 for $5 off, or 20.0 for 20%
```

Update `SaleCreate`:
```python
class SaleCreate(BaseModel):
    items: List[CartItem]
    payment_method: str
    cash_tendered: Optional[Decimal] = None
    card_transaction_id: Optional[str] = None
    receipt_email: Optional[str] = None
    gift_card_barcode: Optional[str] = None
    gift_card_amount: Optional[Decimal] = None
    cart_discount_type: Optional[str] = None    # 'dollar' or 'percent'
    cart_discount_value: Optional[float] = None
```

Update `SaleItemResponse` — add:
```python
discount_type: Optional[str] = None
discount_value: Optional[Decimal] = None
discount_amount: Optional[Decimal] = None
```

Update `SaleResponse` — add:
```python
discount_type: Optional[str] = None
discount_value: Optional[Decimal] = None
discount_amount: Optional[Decimal] = None
```

### 1E. Update sale processing in POS router

File: `app/routers/pos.py`

In the sale creation endpoint (the main checkout function), after calculating `line_total` for each item, apply per-item discounts:

```python
# Per-item discount
item_discount_type = cart_item.discount_type
item_discount_value = Decimal(str(cart_item.discount_value)) if cart_item.discount_value else Decimal("0")
item_discount_amount = Decimal("0")

if item_discount_type == 'dollar':
    item_discount_amount = min(item_discount_value, line_total)
elif item_discount_type == 'percent':
    item_discount_amount = (line_total * item_discount_value / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    item_discount_amount = min(item_discount_amount, line_total)

line_total_after_discount = (line_total - item_discount_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)
```

Use `line_total_after_discount` instead of `line_total` for the subtotal sum and tax calculation.

Then apply cart-wide discount AFTER summing line totals but BEFORE calculating tax:
```python
cart_discount_amount = Decimal("0")
if data.cart_discount_type == 'dollar' and data.cart_discount_value:
    cart_discount_amount = min(Decimal(str(data.cart_discount_value)), subtotal)
elif data.cart_discount_type == 'percent' and data.cart_discount_value:
    cart_discount_amount = (subtotal * Decimal(str(data.cart_discount_value)) / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    cart_discount_amount = min(cart_discount_amount, subtotal)

subtotal_after_discount = subtotal - cart_discount_amount
```

Tax should be calculated on `subtotal_after_discount` (only taxable portion), not the original subtotal.

Store the discount info in the SaleItem and Sale records.

---

## PART 2: Frontend — POS UI changes

File: `frontend/pos/index.html`

### 2A. Per-item discount button in cart rows

In `renderCart()`, add a small discount button on each cart row. When clicked, show a small inline form or modal asking:
- Discount type: `$` or `%` (two toggle buttons)
- Discount value: number input
- Apply / Remove buttons

Store discounts in the cart array: `cart[i].discountType` and `cart[i].discountValue`.

When a discount is applied to an item, show it in the cart row:
```
Vintage Lamp          $45.00
  -20% discount       -$9.00  → $36.00
```

### 2B. Cart-wide discount

Add a "Discount" button near the subtotal/total area (maybe next to the Clear/Hold buttons or below the subtotal line). When clicked, show a small modal:
- Discount type: `$` or `%`
- Value input
- Apply / Clear

Store as `cartDiscountType` and `cartDiscountValue` variables.

Show the discount as a line in the totals area between subtotal and tax:
```
Subtotal:      $120.00
Discount (10%): -$12.00
Tax (5%):        $5.40
Total:         $113.40
```

### 2C. Update `calcTotals()`

The function needs to account for both per-item and cart-wide discounts:

```javascript
function calcTotals() {
    let subtotal = 0;
    let totalItemDiscounts = 0;

    for (const entry of cart) {
        const lineTotal = getActivePrice(entry.item) * entry.quantity;
        let itemDiscount = 0;
        if (entry.discountType === 'dollar') {
            itemDiscount = Math.min(entry.discountValue || 0, lineTotal);
        } else if (entry.discountType === 'percent') {
            itemDiscount = Math.min(lineTotal * (entry.discountValue || 0) / 100, lineTotal);
        }
        entry.calculatedDiscount = Math.round(itemDiscount * 100) / 100;
        subtotal += lineTotal - itemDiscount;
        totalItemDiscounts += itemDiscount;
    }

    // Cart-wide discount
    let cartDiscount = 0;
    if (cartDiscountType === 'dollar') {
        cartDiscount = Math.min(cartDiscountValue || 0, subtotal);
    } else if (cartDiscountType === 'percent') {
        cartDiscount = Math.min(subtotal * (cartDiscountValue || 0) / 100, subtotal);
    }
    cartDiscount = Math.round(cartDiscount * 100) / 100;

    const discountedSubtotal = subtotal - cartDiscount;

    // Tax only on non-exempt items (after discounts)
    // This is approximate for display — backend does precise calculation
    let taxableAmount = 0;
    for (const entry of cart) {
        if (!entry.item.is_tax_exempt) {
            const lineTotal = getActivePrice(entry.item) * entry.quantity;
            const itemDiscount = entry.calculatedDiscount || 0;
            taxableAmount += lineTotal - itemDiscount;
        }
    }
    // Proportionally reduce taxable amount by cart discount
    if (subtotal > 0 && cartDiscount > 0) {
        taxableAmount = taxableAmount * (1 - cartDiscount / subtotal);
    }

    const taxAmount = taxableAmount * TAX_RATE;
    const total = discountedSubtotal + taxAmount;

    return {
        subtotal: Math.round((subtotal + totalItemDiscounts) * 100) / 100,  // original subtotal before any discounts
        itemDiscounts: Math.round(totalItemDiscounts * 100) / 100,
        cartDiscount: cartDiscount,
        taxAmount: Math.round(taxAmount * 100) / 100,
        total: Math.round(total * 100) / 100,
    };
}
```

### 2D. Update `buildSalePayload()`

Include discount info in the payload sent to the backend:

```javascript
function buildSalePayload(paymentMethod) {
    const payload = {
        items: cart.map(({ item, quantity, discountType, discountValue }) => ({
            barcode: item.barcode,
            quantity,
            discount_type: discountType || null,
            discount_value: discountValue || null,
        })),
        payment_method: paymentMethod,
    };
    if (cartDiscountType && cartDiscountValue) {
        payload.cart_discount_type = cartDiscountType;
        payload.cart_discount_value = cartDiscountValue;
    }
    return payload;
}
```

### 2E. Show discounts on receipt

In `showReceiptModal()`, show discount lines for any discounted items and the cart-wide discount.

### 2F. Reset discounts on new sale

In `startNewSale()` or `clearCart()`, reset `cartDiscountType = null` and `cartDiscountValue = 0`.

---

## PART 3: Totals display area

Update the totals section in the HTML. Currently it shows Subtotal / Tax / Total. Add a discount line between subtotal and tax that only appears when discounts are active.

---

## Test
1. Add item, apply $5 discount → price drops by $5, tax adjusts
2. Add item, apply 20% discount → price drops by 20%, tax adjusts
3. Apply 10% cart discount → all items discounted proportionally, shown in totals
4. Mix item discount + cart discount → both apply correctly
5. Tax-exempt items with discount → no tax on that item
6. Receipt shows all discounts clearly
7. Void a discounted sale → works normally
8. Commit and push to main
