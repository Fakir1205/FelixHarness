from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from decimal import Decimal

router = APIRouter(
    prefix="/orders",
    tags=["orders"]
)

class OrderItem(BaseModel):
    price: Decimal
    quantity: int

class OrderQuoteRequest(BaseModel):
    items: list[OrderItem]

class OrderQuoteResponse(BaseModel):
    total_price: Decimal

@router.post("/quote", response_model=OrderQuoteResponse)
async def quote_order(request: OrderQuoteRequest):
    total_price = sum(item.price * item.quantity for item in request.items)
    return OrderQuoteResponse(total_price=total_price)