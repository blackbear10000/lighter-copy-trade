"""
Trading service that orchestrates the trade execution flow.
"""

import lighter
import asyncio
from typing import Dict, Optional, List
from decimal import Decimal

from src.config import get_config, AccountConfig
from src.services.market_service import get_market_service
from src.services.position_service import PositionService
from src.services.order_service import OrderService
from src.monitoring.health_check import get_health_monitor
from src.notifications.telegram import get_telegram_service
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class TradingService:
    """Service that orchestrates trade execution."""
    
    def __init__(self):
        self.config = get_config()
        self.market_service = get_market_service()
        self.position_service = PositionService()
        self.order_service = OrderService()
        self.health_monitor = get_health_monitor()
        self.telegram_service = get_telegram_service()
    
    async def get_account(self, account_index: int) -> Optional[AccountConfig]:
        """Get account configuration by index."""
        for account in self.config.accounts:
            if account.index == account_index:
                return account
        return None
    
    async def get_account_info(self, account_index: int) -> Optional[Dict]:
        """Get account information from Lighter API."""
        try:
            api_client = lighter.ApiClient(
                configuration=lighter.Configuration(host=self.config.base_url)
            )
            account_api = lighter.AccountApi(api_client)
            account = await account_api.account(by="index", value=str(account_index))
            
            if hasattr(account, 'to_dict'):
                account_dict = account.to_dict()
            else:
                account_dict = account
            
            await api_client.close()
            return account_dict
        except Exception as e:
            logger.error(f"Error getting account info: {e}", exc_info=True)
            return None
    
    async def get_stop_loss_orders(
        self,
        account_index: int,
        account: AccountConfig,
        market_ids: List[int]
    ) -> List[Dict]:
        """
        Get stop loss orders for the account across specified markets.
        
        Args:
            account_index: Account index
            account: Account configuration
            market_ids: List of market IDs to query
            
        Returns:
            List of stop loss order dictionaries
        """
        stop_loss_orders = []
        
        try:
            # Create signer client for authentication
            signer_client = await self.order_service.create_signer_client(account)
            
            try:
                api_client = lighter.ApiClient(
                    configuration=lighter.Configuration(host=self.config.base_url)
                )
                order_api = lighter.OrderApi(api_client)
                
                # Query active orders for each market
                for market_id in market_ids:
                    try:
                        # Generate auth token using signer client
                        auth_token, error = signer_client.create_auth_token_with_expiry()
                        if error:
                            logger.warning(f"Error creating auth token for market {market_id}: {error}")
                            continue
                        
                        # Get active orders for this market
                        orders_response = await order_api.account_active_orders(
                            account_index=account_index,
                            market_id=market_id,
                            auth=auth_token
                        )
                        
                        # Convert response to dict
                        if hasattr(orders_response, 'to_dict'):
                            orders_dict = orders_response.to_dict()
                        else:
                            orders_dict = orders_response
                        
                        # Extract orders list
                        orders = []
                        if isinstance(orders_dict, dict):
                            orders = orders_dict.get('orders', [])
                        elif hasattr(orders_response, 'orders'):
                            # If it's a model object, access the orders attribute
                            orders_list = orders_response.orders
                            if orders_list:
                                orders = [order.to_dict() if hasattr(order, 'to_dict') else order for order in orders_list]
                        
                        logger.debug(f"Found {len(orders)} orders for market {market_id}")
                        
                        # Filter stop loss orders
                        for order in orders:
                            # Handle both dict and model object
                            if hasattr(order, 'to_dict'):
                                order_dict = order.to_dict()
                            else:
                                order_dict = order
                            
                            order_type = order_dict.get('type', '')
                            logger.debug(f"Order type: {order_type}, order: {order_dict}")
                            
                            if order_type in ['stop-loss', 'stop-loss-limit']:
                                # Get market symbol
                                market_info = await self.market_service.get_market_info(market_id)
                                symbol = market_info.get('symbol', f'ID{market_id}') if market_info else f'ID{market_id}'
                                
                                stop_loss_orders.append({
                                    'order_index': order_dict.get('order_index', 0),
                                    'order_id': order_dict.get('order_id', ''),
                                    'market_id': market_id,
                                    'symbol': symbol,
                                    'trigger_price': str(order_dict.get('trigger_price', '0')),
                                    'price': str(order_dict.get('price', '0')) if order_dict.get('price') else None,
                                    'base_amount': str(order_dict.get('initial_base_amount', '0')),
                                    'remaining_base_amount': str(order_dict.get('remaining_base_amount', '0')),
                                    'order_type': order_type,
                                    'status': order_dict.get('status', 'unknown'),
                                    'reduce_only': order_dict.get('reduce_only', False),
                                })
                        
                        logger.info(f"Found {len([o for o in stop_loss_orders if o.get('market_id') == market_id])} stop loss orders for market {market_id}")
                    except Exception as e:
                        logger.warning(f"Error querying orders for market {market_id}: {e}")
                        continue
                
                await api_client.close()
                
            finally:
                await signer_client.close()
                
        except Exception as e:
            logger.error(f"Error getting stop loss orders: {e}", exc_info=True)
        
        return stop_loss_orders
    
    async def get_current_price(self, market_id: int) -> Optional[float]:
        """Get current market price from order book."""
        try:
            api_client = lighter.ApiClient(
                configuration=lighter.Configuration(host=self.config.base_url)
            )
            order_api = lighter.OrderApi(api_client)
            order_book_orders = await order_api.order_book_orders(market_id, 1)
            
            # Get best bid/ask price
            # Price is returned as string like "0.143152", convert directly to float
            if order_book_orders.bids and len(order_book_orders.bids) > 0:
                bid_price_str = order_book_orders.bids[0].price
                bid_price = float(bid_price_str) if bid_price_str else None
            else:
                bid_price = None
            
            if order_book_orders.asks and len(order_book_orders.asks) > 0:
                ask_price_str = order_book_orders.asks[0].price
                ask_price = float(ask_price_str) if ask_price_str else None
            else:
                ask_price = None
            
            await api_client.close()
            
            # Use mid price if available
            if bid_price and ask_price:
                return (bid_price + ask_price) / 2
            elif bid_price:
                return bid_price
            elif ask_price:
                return ask_price
            else:
                return None
                
        except Exception as e:
            logger.error(f"Error getting current price: {e}", exc_info=True)
            return None
    
    def convert_price_to_integer(self, price: float, price_decimals: int) -> int:
        """Convert price to integer format with precision."""
        multiplier = 10 ** price_decimals
        return int(price * multiplier)
    
    def convert_base_amount_to_integer(self, base_amount: float, size_decimals: int) -> int:
        """Convert base amount to integer format with precision."""
        multiplier = 10 ** size_decimals
        return int(base_amount * multiplier)
    
    async def calculate_stop_loss_price(
        self,
        avg_entry_price: float,
        position_size: float,
        position_value: float,
        allocated_margin: float,
        initial_margin_fraction: float,
        is_long: bool,
        price_decimals: int
    ) -> int:
        """
        Calculate stop loss price based on actual margin invested, not leveraged position value.
        
        Args:
            avg_entry_price: Average entry price
            position_size: Position size (absolute value)
            position_value: Position value (leveraged value)
            allocated_margin: Allocated margin for this position (0 for cross margin)
            initial_margin_fraction: Initial margin fraction percentage
            is_long: True for long position, False for short
            price_decimals: Price precision decimals
            
        Returns:
            Stop loss price in integer format
        """
        # Calculate stop loss price using formula: avg_entry_price * (1 - initial_margin_fraction * STOP_LOSS_RATIO)
        # initial_margin_fraction is a percentage (e.g., 33.33 means 33.33%)
        margin_fraction = initial_margin_fraction / 100.0 if initial_margin_fraction > 0 else 0.3333
        
        # Calculate stop loss ratio based on margin fraction
        # For long: stop_loss_price = avg_entry_price * (1 - margin_fraction * stop_loss_ratio)
        # For short: stop_loss_price = avg_entry_price * (1 + margin_fraction * stop_loss_ratio)
        if is_long:
            stop_loss_price = avg_entry_price * (1 - margin_fraction * self.config.stop_loss_ratio)
        else:
            stop_loss_price = avg_entry_price * (1 + margin_fraction * self.config.stop_loss_ratio)
        
        # Fallback validation: if calculated price is invalid, use simple ratio
        if stop_loss_price <= 0:
            logger.warning(
                f"Invalid stop loss price calculated: {stop_loss_price}, "
                f"using fallback calculation (margin_fraction={margin_fraction})"
            )
            if is_long:
                stop_loss_price = avg_entry_price * (1 - self.config.stop_loss_ratio)
            else:
                stop_loss_price = avg_entry_price * (1 + self.config.stop_loss_ratio)
        
        logger.debug(
            f"Stop loss calculation: avg_entry_price={avg_entry_price:.6f}, "
            f"initial_margin_fraction={initial_margin_fraction:.2f}%, "
            f"margin_fraction={margin_fraction:.4f}, "
            f"stop_loss_ratio={self.config.stop_loss_ratio:.4f}, "
            f"stop_loss_price={stop_loss_price:.6f}"
        )
        
        return self.convert_price_to_integer(stop_loss_price, price_decimals)
    
    async def execute_trade(self, request_data: Dict) -> Dict:
        """
        Execute a trade request.
        
        Args:
            request_data: Trade request data dictionary
            
        Returns:
            Result dictionary
        """
        request_id = request_data.get('request_id', 'unknown')
        account_index = request_data.get('account_index')
        market_id = request_data.get('market_id')
        symbol = request_data.get('symbol')
        trade_type = request_data.get('trade_type')
        reference_position_ratio = request_data.get('reference_position_ratio')
        override_base_amount = request_data.get('override_base_amount')
        override_quote_amount = request_data.get('override_quote_amount')
        override_context = request_data.get('override_context')
        using_override_size = override_base_amount is not None or override_quote_amount is not None
        
        logger.info(f"Executing trade request {request_id}: account={account_index}, market_id={market_id}, symbol={symbol}, type={trade_type}")
        
        try:
            # Validate account
            account = await self.get_account(account_index)
            if not account:
                error_msg = f"Account {account_index} not found"
                await self.telegram_service.notify_error(
                    "Account Not Found",
                    error_msg,
                    {"request_id": request_id, "account_index": account_index}
                )
                return {"success": False, "error": error_msg}
            
            # Validate and resolve market
            try:
                market_result = await self.market_service.validate_market(
                    market_id=market_id,
                    symbol=symbol
                )
                resolved_market_id = market_result['market_id']
                market_info = market_result['market_info']
                resolved_symbol = market_info.get('symbol', symbol or f"ID{resolved_market_id}")
            except ValueError as e:
                error_msg = str(e)
                await self.telegram_service.notify_error(
                    "Market Validation Error",
                    error_msg,
                    {"request_id": request_id, "market_id": market_id, "symbol": symbol}
                )
                return {"success": False, "error": error_msg}
            
            # Get account info
            account_info = await self.get_account_info(account_index)
            if not account_info:
                error_msg = "Could not retrieve account information"
                await self.telegram_service.notify_error(
                    "Account Info Error",
                    error_msg,
                    {"request_id": request_id, "account_index": account_index}
                )
                return {"success": False, "error": error_msg}
            
            # Extract available balance from account info
            # Account info structure: accounts[0].available_balance
            accounts = account_info.get('accounts', [])
            if not accounts or len(accounts) == 0:
                error_msg = "No account data found in response"
                await self.telegram_service.notify_error(
                    "Account Data Error",
                    error_msg,
                    {"request_id": request_id, "account_index": account_index}
                )
                return {"success": False, "error": error_msg}
            
            account_data = accounts[0]
            available_balance = float(account_data.get('available_balance', 0))
            total_asset_value = float(account_data.get('total_asset_value', 0))
            min_base_amount = float(market_info.get('min_base_amount', 0))
            min_quote_amount = float(market_info.get('min_quote_amount', 0))
            price_decimals = market_info.get('supported_price_decimals', 6)
            size_decimals = market_info.get('supported_size_decimals', 0)
            
            logger.info(
                f"Account balance info: total_assets={total_asset_value}, "
                f"available_balance={available_balance}, reference_ratio={reference_position_ratio}, "
                f"scaling_factor={self.config.scaling_factor}"
            )
            
            # Handle close trade type
            if trade_type == "close":
                return await self._execute_close_trade(
                    account, resolved_market_id, resolved_symbol, account_info
                )
            
            # Get current price
            current_price = await self.get_current_price(resolved_market_id)
            if current_price is None:
                error_msg = "Could not get current market price"
                await self.telegram_service.notify_error(
                    "Price Error",
                    error_msg,
                    {"request_id": request_id, "market_id": resolved_market_id}
                )
                return {"success": False, "error": error_msg}
            
            logger.info(
                f"Price info: current_price={current_price}, market_id={resolved_market_id}, "
                f"symbol={resolved_symbol}"
            )
            
            if using_override_size:
                base_amount = float(override_base_amount) if override_base_amount is not None else 0.0
                quote_amount = float(override_quote_amount) if override_quote_amount is not None else None
                
                if base_amount <= 0 and (quote_amount is None or quote_amount <= 0):
                    error_msg = (
                        "Override adjustment amount is invalid. Provide a positive base or quote amount."
                    )
                    await self.telegram_service.notify_error(
                        "Adjustment Size Error",
                        error_msg,
                        {
                            "request_id": request_id,
                            "account_index": account_index,
                            "market_id": resolved_market_id,
                            "symbol": resolved_symbol,
                            "override_context": override_context,
                        }
                    )
                    return {"success": False, "error": error_msg, "no_retry": True}
                
                if base_amount <= 0:
                    if quote_amount is None or current_price <= 0:
                        error_msg = "Cannot derive base amount from quote for override adjustment"
                        await self.telegram_service.notify_error(
                            "Adjustment Size Error",
                            error_msg,
                            {
                                "request_id": request_id,
                                "account_index": account_index,
                                "market_id": resolved_market_id,
                                "symbol": resolved_symbol,
                                "override_context": override_context,
                            }
                        )
                        return {"success": False, "error": error_msg, "no_retry": True}
                    base_amount = quote_amount / current_price
                
                base_amount = abs(base_amount)
                base_amount = self.position_service.format_amount(base_amount, size_decimals)
                if base_amount <= 0:
                    error_msg = "Rounded adjustment amount is zero; increase percentage or position size."
                    await self.telegram_service.notify_error(
                        "Adjustment Size Error",
                        error_msg,
                        {
                            "request_id": request_id,
                            "account_index": account_index,
                            "market_id": resolved_market_id,
                            "symbol": resolved_symbol,
                            "override_context": override_context,
                        }
                    )
                    return {"success": False, "error": error_msg, "no_retry": True}
                
                quote_amount = base_amount * current_price
                insufficient_balance_flag = quote_amount > available_balance
                
                if quote_amount < min_quote_amount or base_amount < min_base_amount:
                    error_msg = (
                        f"Override adjustment size below minimum: base={base_amount:.6f} "
                        f"(min={min_base_amount:.6f}), quote={quote_amount:.6f} (min={min_quote_amount:.6f})"
                    )
                    logger.warning(f"Override position size below minimum, skipping trade: {error_msg}")
                    await self.telegram_service.notify_error(
                        "Insufficient Position Size",
                        error_msg,
                        {
                            "request_id": request_id,
                            "account_index": account_index,
                            "market_id": resolved_market_id,
                            "symbol": resolved_symbol,
                            "trade_type": trade_type,
                            "override_context": override_context,
                            "calculated_quote_amount": quote_amount,
                            "calculated_base_amount": base_amount,
                            "min_base_amount": min_base_amount,
                            "min_quote_amount": min_quote_amount,
                            "current_price": current_price,
                        }
                    )
                    return {
                        "success": False,
                        "error": error_msg,
                        "no_retry": True
                    }
                
                position_size = {
                    'base_amount': base_amount,
                    'quote_amount': quote_amount,
                    'insufficient_balance': insufficient_balance_flag
                }
                
                logger.info(
                    f"Override position size applied: base={base_amount}, quote={quote_amount}, "
                    f"insufficient_balance={insufficient_balance_flag}, context={override_context}"
                )
            else:
                # Calculate position size based on total assets
                position_size = self.position_service.calculate_position_size(
                    total_assets=total_asset_value,
                    available_balance=available_balance,
                    reference_position_ratio=reference_position_ratio,
                    market_info=market_info,
                    current_price=current_price
                )
                
                logger.info(
                    f"Position calculation: total_assets={total_asset_value}, "
                    f"available_balance={available_balance}, "
                    f"quote_amount_calc={total_asset_value * reference_position_ratio * self.config.scaling_factor}, "
                    f"position_size={position_size}"
                )
            
            # Check if insufficient balance and send warning
            if position_size and position_size.get('insufficient_balance', False):
                required_amount = position_size.get('quote_amount', 0)
                shortfall = required_amount - available_balance
                warning_msg = (
                    f"Insufficient available balance: Required {required_amount:.2f} USDC, "
                    f"but only {available_balance:.2f} USDC available. Shortfall: {shortfall:.2f} USDC. "
                    f"Trade will proceed if sufficient margin is available."
                )
                logger.warning(warning_msg)
                await self.telegram_service.notify_error(
                    "Insufficient Available Balance Warning",
                    warning_msg,
                    {
                        "request_id": request_id,
                        "account_index": account_index,
                        "market_id": resolved_market_id,
                        "symbol": resolved_symbol,
                        "required_amount": required_amount,
                        "available_balance": available_balance,
                        "shortfall": shortfall,
                        "total_assets": total_asset_value,
                    }
                )
            
            if position_size is None:
                # Calculate what the quote_amount would have been to provide better error message
                calculated_quote_amount = total_asset_value * reference_position_ratio * self.config.scaling_factor
                
                # Determine which requirement failed
                if calculated_quote_amount < min_quote_amount:
                    error_msg = (
                        f"Calculated quote amount ({calculated_quote_amount:.6f}) is below minimum "
                        f"({min_quote_amount:.6f}). Total assets ({total_asset_value:.6f}) * "
                        f"ratio ({reference_position_ratio}) * scaling ({self.config.scaling_factor}) = "
                        f"{calculated_quote_amount:.6f}"
                    )
                else:
                    # Base amount would be the issue
                    calculated_base_amount = calculated_quote_amount / current_price if current_price > 0 else 0
                    error_msg = (
                        f"Calculated base amount ({calculated_base_amount:.6f}) is below minimum "
                        f"({min_base_amount:.6f}). Quote amount ({calculated_quote_amount:.6f}) is sufficient, "
                        f"but base amount is too small at current price ({current_price:.6f})"
                    )
                
                logger.warning(f"Position size below minimum, skipping trade: {error_msg}")
                
                # Send Telegram notification for insufficient size
                await self.telegram_service.notify_error(
                    "Insufficient Position Size",
                    error_msg,
                    {
                        "request_id": request_id,
                        "account_index": account_index,
                        "market_id": resolved_market_id,
                        "symbol": resolved_symbol,
                        "trade_type": trade_type,
                        "reference_position_ratio": reference_position_ratio,
                        "total_assets": total_asset_value,
                        "available_balance": available_balance,
                        "calculated_quote_amount": calculated_quote_amount,
                        "calculated_base_amount": calculated_quote_amount / current_price if current_price > 0 else 0,
                        "min_base_amount": min_base_amount,
                        "min_quote_amount": min_quote_amount,
                        "current_price": current_price,
                        "scaling_factor": self.config.scaling_factor,
                    }
                )
                
                # Return with no_retry flag to skip retry mechanism
                return {
                    "success": False,
                    "error": error_msg,
                    "no_retry": True  # Flag to indicate this error should not be retried
                }
            
            # Determine order direction
            is_long = trade_type == "long"
            is_ask = not is_long  # is_ask=True means sell (short), is_ask=False means buy (long)
            
            # Check current position direction before executing trade
            # This is to determine if we should update stop loss after the trade
            current_position_direction = None
            accounts = account_info.get('accounts', [])
            if accounts and len(accounts) > 0:
                positions = accounts[0].get('positions', [])
                for pos in positions:
                    if pos.get('market_id') == resolved_market_id:
                        position_size_before = float(pos.get('position', 0))
                        if position_size_before != 0:
                            # sign: 1 for long, -1 for short
                            current_position_direction = pos.get('sign', 1)
                        break
            
            # Convert amounts to integer format
            base_amount_int = self.convert_base_amount_to_integer(
                position_size['base_amount'],
                size_decimals
            )
            price_int = self.convert_price_to_integer(current_price, price_decimals)
            
            # Create signer client
            signer_client = await self.order_service.create_signer_client(account)
            
            try:
                # Execute market order
                order, tx_hash, error = await self.order_service.execute_market_order(
                    signer_client=signer_client,
                    market_id=resolved_market_id,
                    base_amount=base_amount_int,
                    is_ask=is_ask,
                    max_slippage=self.config.max_slippage
                )
                
                if error:
                    raise Exception(f"Order execution failed: {error}")
                
                # Wait a bit for the order to be processed and account info to update
                await asyncio.sleep(3)
                
                # Get updated account info for position data
                updated_account_info = await self.get_account_info(account_index)
                
                # Send notification
                await self.telegram_service.notify_order_opening(
                    account_index=account_index,
                    market_id=resolved_market_id,
                    symbol=resolved_symbol,
                    trade_type=trade_type,
                    base_amount=position_size['base_amount'],
                    quote_amount=position_size['quote_amount'],
                    price=current_price,
                    position_info=updated_account_info
                )
                
                # Update stop loss only if:
                # 1. This is an opening trade (no existing position), OR
                # 2. This is an adding trade (same direction as existing position)
                # Do NOT update stop loss if this is a reducing/closing trade (opposite direction)
                should_update_stop_loss = False
                if trade_type in ["long", "short"]:
                    if current_position_direction is None:
                        # No existing position, this is an opening trade - update stop loss
                        should_update_stop_loss = True
                        logger.info(f"Opening new {trade_type} position, will update stop loss")
                    else:
                        # Check if trade direction matches current position direction
                        # sign: 1 for long, -1 for short
                        trade_sign = 1 if is_long else -1
                        if trade_sign == current_position_direction:
                            # Same direction - this is an adding trade - update stop loss
                            should_update_stop_loss = True
                            logger.info(f"Adding to existing {trade_type} position, will update stop loss")
                        else:
                            # Opposite direction - this is a reducing/closing trade - do NOT update stop loss
                            should_update_stop_loss = False
                            logger.info(
                                f"Reducing/closing position (existing: {current_position_direction}, "
                                f"trade: {trade_sign}), will NOT update stop loss"
                            )
                
                if should_update_stop_loss:
                    await self._update_stop_loss(
                        signer_client,
                        resolved_market_id,
                        resolved_symbol,
                        is_long,
                        price_decimals,
                        size_decimals,
                        updated_account_info
                    )
                
                logger.info(f"Trade executed successfully: request_id={request_id}, tx_hash={tx_hash}")
                return {
                    "success": True,
                    "tx_hash": tx_hash,
                    "market_id": resolved_market_id,
                    "symbol": resolved_symbol,
                    "base_amount": position_size['base_amount'],
                    "quote_amount": position_size['quote_amount'],
                    "price": current_price
                }
                
            finally:
                await signer_client.close()
                
        except Exception as e:
            error_msg = f"Trade execution error: {str(e)}"
            logger.error(f"{error_msg} (request_id={request_id})", exc_info=True)
            await self.telegram_service.notify_error(
                "Trade Execution Error",
                error_msg,
                {"request_id": request_id, "request_data": request_data}
            )
            return {"success": False, "error": error_msg}
    
    async def _execute_close_trade(
        self,
        account: AccountConfig,
        market_id: int,
        symbol: str,
        account_info: Dict
    ) -> Dict:
        """Execute a close trade (close entire position)."""
        try:
            # Extract account data from response structure
            accounts = account_info.get('accounts', [])
            if not accounts or len(accounts) == 0:
                return {"success": False, "error": "No account data found in response"}
            
            account_data = accounts[0]
            
            # Find position for this market (before closing)
            positions = account_data.get('positions', [])
            position = None
            for pos in positions:
                if pos.get('market_id') == market_id:
                    position = pos
                    break
            
            if not position:
                return {"success": False, "error": f"No position found for market {market_id}"}
            
            position_size = float(position.get('position', 0))
            if position_size == 0:
                return {"success": False, "error": "Position size is zero"}
            
            # Store PnL information before closing
            unrealized_pnl_before = float(position.get('unrealized_pnl', 0))
            realized_pnl_before = float(position.get('realized_pnl', 0))
            avg_entry_price = float(position.get('avg_entry_price', 0))
            
            # Get market info for precision
            market_info = await self.market_service.get_market_info(market_id)
            if not market_info:
                return {"success": False, "error": "Could not get market information"}
            
            # Get current price
            current_price = await self.get_current_price(market_id)
            if current_price is None:
                return {"success": False, "error": "Could not get current market price"}
            
            # Determine direction (sign: 1 for long, -1 for short)
            sign = position.get('sign', 1)
            is_long = sign == 1
            is_ask = is_long  # Close long = sell, close short = buy
            
            # Convert to integer format
            price_decimals = market_info.get('supported_price_decimals', 6)
            size_decimals = market_info.get('supported_size_decimals', 0)
            
            base_amount_int = self.convert_base_amount_to_integer(
                abs(position_size),
                size_decimals
            )
            price_int = self.convert_price_to_integer(current_price, price_decimals)
            
            # Create signer client
            signer_client = await self.order_service.create_signer_client(account)
            
            try:
                # Execute market order to close position
                order, tx_hash, error = await self.order_service.execute_market_order(
                    signer_client=signer_client,
                    market_id=market_id,
                    base_amount=base_amount_int,
                    is_ask=is_ask,
                    max_slippage=self.config.max_slippage
                )
                
                if error:
                    raise Exception(f"Close order execution failed: {error}")
                
                # Wait a bit for the order to be processed
                await asyncio.sleep(3)
                
                # Get updated account info to check final PnL
                updated_account_info = await self.get_account_info(account.index)
                
                # Calculate PnL: When closing a position, the unrealized PnL becomes realized PnL
                # The total realized PnL = previous realized PnL + unrealized PnL at close time
                accounts_updated = updated_account_info.get('accounts', []) if updated_account_info else []
                unrealized_pnl = 0.0  # Position closed, no unrealized PnL
                realized_pnl = realized_pnl_before + unrealized_pnl_before  # Add unrealized to realized
                
                # Try to get updated realized PnL from account info if position still exists (partial close)
                if accounts_updated and len(accounts_updated) > 0:
                    updated_positions = accounts_updated[0].get('positions', [])
                    for pos in updated_positions:
                        if pos.get('market_id') == market_id:
                            # Position still exists (partial close), use its PnL
                            unrealized_pnl = float(pos.get('unrealized_pnl', 0))
                            # For partial close, we need to calculate the realized portion
                            # The realized PnL should be the difference
                            updated_realized_pnl = float(pos.get('realized_pnl', 0))
                            # If the updated realized PnL is greater, use it
                            if updated_realized_pnl > realized_pnl_before:
                                realized_pnl = updated_realized_pnl
                            else:
                                # Otherwise, calculate: previous realized + (previous unrealized - current unrealized)
                                realized_pnl = realized_pnl_before + (unrealized_pnl_before - unrealized_pnl)
                            break
                
                # Calculate the realized PnL from this close operation
                # This is the PnL that was realized by closing this position
                realized_pnl_from_close = realized_pnl - realized_pnl_before
                
                # Create position info dict for notification with detailed PnL info
                position_info_for_notification = {
                    'accounts': [{
                        'positions': [{
                            'market_id': market_id,
                            'unrealized_pnl': str(unrealized_pnl),
                            'realized_pnl': str(realized_pnl),
                            'realized_pnl_from_close': str(realized_pnl_from_close),
                            'realized_pnl_before': str(realized_pnl_before),
                            'unrealized_pnl_before': str(unrealized_pnl_before),
                        }]
                    }]
                }
                
                logger.info(
                    f"Close PnL calculation: unrealized_before={unrealized_pnl_before}, "
                    f"realized_before={realized_pnl_before}, "
                    f"final_realized={realized_pnl}, final_unrealized={unrealized_pnl}, "
                    f"realized_from_close={realized_pnl_from_close}"
                )
                
                # Send notification
                await self.telegram_service.notify_order_closing(
                    account_index=account.index,
                    market_id=market_id,
                    symbol=symbol,
                    base_amount=abs(position_size),
                    quote_amount=abs(position_size) * current_price,
                    price=current_price,
                    position_info=position_info_for_notification
                )
                
                logger.info(f"Position closed successfully: market_id={market_id}, tx_hash={tx_hash}")
                return {
                    "success": True,
                    "tx_hash": tx_hash,
                    "market_id": market_id,
                    "symbol": symbol,
                    "base_amount": abs(position_size)
                }
                
            finally:
                await signer_client.close()
                
        except Exception as e:
            error_msg = f"Close trade error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {"success": False, "error": error_msg}
    
    async def _update_stop_loss(
        self,
        signer_client: lighter.SignerClient,
        market_id: int,
        symbol: str,
        is_long: bool,
        price_decimals: int,
        size_decimals: int,
        account_info: Dict
    ):
        """Update stop loss for the position."""
        try:
            # Extract account data from response structure
            accounts = account_info.get('accounts', [])
            if not accounts or len(accounts) == 0:
                logger.warning("No account data found for stop loss update")
                return
            
            account_data = accounts[0]
            
            # Find position for this market
            positions = account_data.get('positions', [])
            position = None
            for pos in positions:
                if pos.get('market_id') == market_id:
                    position = pos
                    break
            
            if not position:
                logger.warning(f"No position found for market {market_id}, skipping stop loss update")
                return
            
            position_size = float(position.get('position', 0))
            if position_size == 0:
                logger.warning(f"Position size is zero for market {market_id}, skipping stop loss update")
                return
            
            avg_entry_price = float(position.get('avg_entry_price', 0))
            if avg_entry_price == 0:
                logger.warning(f"Average entry price is zero for market {market_id}, skipping stop loss update")
                return
            
            # Cancel existing stop loss orders
            existing_orders = await self.order_service.get_existing_stop_loss_orders(
                signer_client,
                market_id
            )
            
            if existing_orders:
                logger.info(f"Cancelling {len(existing_orders)} existing stop loss orders for market {market_id}")
                for order_index in existing_orders:
                    cancel_result, tx_hash, error = await self.order_service.cancel_order(
                        signer_client,
                        market_id,
                        order_index
                    )
                    if error:
                        logger.warning(f"Failed to cancel stop loss order {order_index}: {error}")
                    else:
                        logger.info(f"Cancelled stop loss order {order_index}: tx_hash={tx_hash}")
            
            # Get position value and margin information
            position_value = float(position.get('position_value', 0))
            allocated_margin = float(position.get('allocated_margin', 0))
            initial_margin_fraction = float(position.get('initial_margin_fraction', 0))
            
            # Calculate stop loss price based on actual margin
            stop_loss_price_int = await self.calculate_stop_loss_price(
                avg_entry_price=avg_entry_price,
                position_size=abs(position_size),
                position_value=position_value,
                allocated_margin=allocated_margin,
                initial_margin_fraction=initial_margin_fraction,
                is_long=is_long,
                price_decimals=price_decimals
            )
            
            # Convert position size to integer
            base_amount_int = self.convert_base_amount_to_integer(
                abs(position_size),
                size_decimals
            )
            
            # Create new stop loss order with slippage tolerance
            await self.order_service.create_stop_loss_order(
                signer_client=signer_client,
                market_id=market_id,
                base_amount=base_amount_int,
                stop_loss_price=stop_loss_price_int,
                is_long=is_long,
                price_decimals=price_decimals
            )
            
            logger.info(f"Stop loss updated for market {market_id}")
            
        except Exception as e:
            logger.error(f"Error updating stop loss: {e}", exc_info=True)
            # Don't fail the trade if stop loss update fails
            await self.telegram_service.notify_error(
                "Stop Loss Update Error",
                str(e),
                {"market_id": market_id, "symbol": symbol}
            )
    
    async def execute_trade_with_retry(self, request_data: Dict) -> Dict:
        """
        Execute trade with retry mechanism.
        
        Args:
            request_data: Trade request data dictionary
            
        Returns:
            Result dictionary
        """
        max_retries = self.config.max_retries
        retry_interval = self.config.retry_interval
        
        for attempt in range(max_retries + 1):
            try:
                result = await self.execute_trade(request_data)
                
                if result.get("success"):
                    return result
                
                # Check if this error should not be retried (e.g., insufficient size)
                if result.get("no_retry", False):
                    logger.info("Error marked as no-retry, skipping retry mechanism")
                    return result
                
                # If not last attempt, wait and retry
                if attempt < max_retries:
                    logger.info(
                        f"Trade failed, retrying ({attempt + 1}/{max_retries}) "
                        f"after {retry_interval}s"
                    )
                    await asyncio.sleep(retry_interval)
                else:
                    # All retries failed
                    error_msg = result.get("error", "Unknown error")
                    await self.telegram_service.notify_error(
                        "Trade Retry Failed",
                        f"All {max_retries} retry attempts failed. Last error: {error_msg}",
                        {"request_data": request_data}
                    )
                    return result
                    
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(f"Trade attempt {attempt + 1} failed: {e}, retrying...")
                    await asyncio.sleep(retry_interval)
                else:
                    error_msg = f"All retry attempts failed. Last error: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    await self.telegram_service.notify_error(
                        "Trade Retry Failed",
                        error_msg,
                        {"request_data": request_data}
                    )
                    return {"success": False, "error": error_msg}
        
        return {"success": False, "error": "Unexpected retry loop exit"}


# Global trading service instance
_trading_service = None


def get_trading_service() -> TradingService:
    """Get the global trading service instance."""
    global _trading_service
    if _trading_service is None:
        _trading_service = TradingService()
    return _trading_service

