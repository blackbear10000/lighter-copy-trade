"""
API routes for the trading system.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from typing import Dict

from src.models.schemas import TradeRequest, TradeResponse, ErrorResponse
from src.api.auth import verify_api_key
from src.services.trading_service import get_trading_service
from src.monitoring.health_check import get_health_monitor
from src.utils.queue_manager import get_queue_manager
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()


@router.post("/api/trade", response_model=TradeResponse, status_code=status.HTTP_200_OK)
async def create_trade(
    request: TradeRequest,
    _: bool = Depends(verify_api_key)
) -> TradeResponse:
    """
    Create a trade request.
    
    The request is queued and processed in the background.
    """
    # Check API health
    health_monitor = get_health_monitor()
    if not health_monitor.is_api_healthy():
        raise HTTPException(
            status_code=503,
            detail="Lighter API is currently unavailable"
        )
    
    # Validate that either market_id or symbol is provided
    if not request.market_id and not request.symbol:
        raise HTTPException(
            status_code=400,
            detail="Either market_id or symbol must be provided"
        )
    
    # Resolve symbol to market_id if needed
    market_id = request.market_id
    symbol = request.symbol
    
    if symbol and not market_id:
        trading_service = get_trading_service()
        try:
            market_result = await trading_service.market_service.validate_market(
                market_id=None,
                symbol=symbol
            )
            market_id = market_result['market_id']
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e)
            )
    
    # Prepare request data
    request_data = {
        "account_index": request.account_index,
        "market_id": market_id,
        "symbol": symbol,
        "trade_type": request.trade_type,
        "reference_position_ratio": request.reference_position_ratio,
    }
    
    # Enqueue request
    queue_manager = get_queue_manager()
    trading_service = get_trading_service()
    
    request_id = await queue_manager.enqueue(
        account_index=request.account_index,
        request_data=request_data,
        handler=trading_service.execute_trade_with_retry
    )
    
    logger.info(f"Trade request enqueued: request_id={request_id}")
    
    return TradeResponse(
        status="success",
        message="request accepted, processing in background",
        request_id=request_id
    )


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    health_monitor = get_health_monitor()
    is_healthy = health_monitor.is_api_healthy()
    
    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "api_healthy": is_healthy
    }

