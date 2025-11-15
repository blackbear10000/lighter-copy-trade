"""
API routes for the trading system.
"""

from fastapi import APIRouter, HTTPException, Depends, status, Path
from typing import Dict

from src.models.schemas import TradeRequest, TradeResponse, ErrorResponse, AccountInfoResponse, PositionInfo, StopLossOrderInfo
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


@router.get("/api/account/{account_index}", response_model=AccountInfoResponse, status_code=status.HTTP_200_OK)
async def get_account_info(
    account_index: int = Path(..., description="Account index to query"),
    _: bool = Depends(verify_api_key)
) -> AccountInfoResponse:
    """
    Get account information including balance, positions, and PnL.
    
    Returns detailed account information from Lighter platform.
    """
    # Check API health
    health_monitor = get_health_monitor()
    if not health_monitor.is_api_healthy():
        raise HTTPException(
            status_code=503,
            detail="Lighter API is currently unavailable"
        )
    
    trading_service = get_trading_service()
    
    # Validate account exists in configuration
    account = await trading_service.get_account(account_index)
    if not account:
        raise HTTPException(
            status_code=404,
            detail=f"Account {account_index} not found in configuration"
        )
    
    # Get account info from Lighter API
    account_info = await trading_service.get_account_info(account_index)
    if not account_info:
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve account information from Lighter API"
        )
    
    # Extract account data
    accounts = account_info.get('accounts', [])
    if not accounts or len(accounts) == 0:
        raise HTTPException(
            status_code=500,
            detail="No account data found in API response"
        )
    
    account_data = accounts[0]
    
    # Format positions
    positions_data = account_data.get('positions', [])
    positions = []
    market_ids = set()  # Collect market IDs for stop loss order query
    for pos in positions_data:
        market_id = pos.get('market_id', 0)
        if market_id:
            market_ids.add(market_id)
        positions.append(PositionInfo(
            market_id=market_id,
            symbol=pos.get('symbol', 'N/A'),
            position=str(pos.get('position', '0')),
            position_value=str(pos.get('position_value', '0')),
            avg_entry_price=str(pos.get('avg_entry_price', '0')),
            unrealized_pnl=str(pos.get('unrealized_pnl', '0')),
            realized_pnl=str(pos.get('realized_pnl', '0')),
            sign=pos.get('sign', 0),
        ))
    
    # Get stop loss orders for markets with positions
    stop_loss_orders_data = []
    if market_ids:
        stop_loss_orders_data = await trading_service.get_stop_loss_orders(
            account_index=account_index,
            account=account,
            market_ids=list(market_ids)
        )
    
    # Format stop loss orders
    stop_loss_orders = []
    for sl_order in stop_loss_orders_data:
        stop_loss_orders.append(StopLossOrderInfo(
            order_index=sl_order.get('order_index', 0),
            order_id=sl_order.get('order_id', ''),
            market_id=sl_order.get('market_id', 0),
            symbol=sl_order.get('symbol', 'N/A'),
            trigger_price=sl_order.get('trigger_price', '0'),
            price=sl_order.get('price'),
            base_amount=sl_order.get('base_amount', '0'),
            remaining_base_amount=sl_order.get('remaining_base_amount', '0'),
            order_type=sl_order.get('order_type', 'stop-loss'),
            status=sl_order.get('status', 'unknown'),
            reduce_only=sl_order.get('reduce_only', False),
        ))
    
    return AccountInfoResponse(
        account_index=account_data.get('index', account_index),
        l1_address=account_data.get('l1_address', ''),
        available_balance=str(account_data.get('available_balance', '0')),
        collateral=str(account_data.get('collateral', '0')),
        total_asset_value=str(account_data.get('total_asset_value', '0')),
        cross_asset_value=str(account_data.get('cross_asset_value', '0')),
        positions=positions,
        stop_loss_orders=stop_loss_orders,
        status=account_data.get('status', 0),
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

