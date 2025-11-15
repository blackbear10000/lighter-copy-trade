"""
Pydantic models for API request/response validation.
"""

from typing import Optional
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

