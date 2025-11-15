"""
Pydantic models for API request/response validation.
"""

from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator


class TradeRequest(BaseModel):
    """Trade request model."""
    account_index: int = Field(..., description="Account index to operate on")
    market_id: Optional[int] = Field(None, description="Market ID for the trading pair")
    symbol: Optional[str] = Field(None, description="Trading pair symbol (e.g., ETH, BTC, RESOLV)")
    trade_type: str = Field(..., description="Trade type: long, short, or close")
    reference_position_ratio: float = Field(..., ge=0, le=1, description="Reference position ratio (1 = 100%)")

    @field_validator('trade_type')
    @classmethod
    def validate_trade_type(cls, v):
        allowed = ["long", "short", "close"]
        if v not in allowed:
            raise ValueError(f"trade_type must be one of {allowed}")
        return v

    @model_validator(mode='after')
    def validate_market_identifier(self):
        """Ensure at least one of market_id or symbol is provided."""
        if not self.market_id and not self.symbol:
            raise ValueError("Either market_id or symbol must be provided")
        return self


class TradeResponse(BaseModel):
    """Trade response model."""
    status: str
    message: str
    request_id: Optional[str] = None
    error_code: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response model."""
    status: str = "error"
    error_code: str
    message: str


class PositionInfo(BaseModel):
    """Position information model."""
    market_id: int
    symbol: str
    position: str
    position_value: str
    avg_entry_price: str
    unrealized_pnl: str
    realized_pnl: str
    sign: int  # 1 for long, -1 for short


class StopLossOrderInfo(BaseModel):
    """Stop loss order information model."""
    order_index: int
    order_id: str
    market_id: int
    symbol: str
    trigger_price: str
    price: Optional[str] = None  # For stop-loss-limit orders
    base_amount: str
    remaining_base_amount: str
    order_type: str  # 'stop-loss' or 'stop-loss-limit'
    status: str
    reduce_only: bool


class AccountInfoResponse(BaseModel):
    """Account information response model."""
    account_index: int
    l1_address: str
    available_balance: str
    collateral: str
    total_asset_value: str
    cross_asset_value: str
    positions: List[PositionInfo]
    stop_loss_orders: List[StopLossOrderInfo]
    status: int  # 0 = inactive, 1 = active

