import math
from fastapi import APIRouter, Depends
from app.routers.auth import get_current_user
from app.models.vendor import Vendor
from app.schemas.sale import PoyntChargeRequest, PoyntChargeResponse, PoyntStatusResponse
from app.services import poynt

router = APIRouter(prefix="/pos", tags=["pos"])


@router.post("/poynt/charge", response_model=PoyntChargeResponse)
async def poynt_charge(
    data: PoyntChargeRequest,
    current_user: Vendor = Depends(get_current_user),
):
    amount_cents = math.ceil(data.amount * 100)
    order_id = await poynt.create_terminal_order(
        amount_cents=amount_cents,
        currency="USD",
        order_ref=data.order_ref,
    )
    return PoyntChargeResponse(poynt_order_id=order_id)


@router.get("/poynt/status/{poynt_order_id}", response_model=PoyntStatusResponse)
async def poynt_status(
    poynt_order_id: str,
    current_user: Vendor = Depends(get_current_user),
):
    result = await poynt.get_transaction_for_order(poynt_order_id)
    return PoyntStatusResponse(
        status=result["status"],
        transaction_id=result.get("transaction_id"),
    )
