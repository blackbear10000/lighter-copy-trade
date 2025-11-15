"""
Trading service that orchestrates the trade execution flow.
"""

import lighter
import asyncio
from typing import Dict, Optional
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
    
    async def get_current_price(self, market_id: int) -> Optional[float]:
        """Get current market price from order book."""
        try:
            api_client = lighter.ApiClient(
                configuration=lighter.Configuration(host=self.config.base_url)
            )
            order_api = lighter.OrderApi(api_client)
            order_book_orders = await order_api.order_book_orders(market_id, 1)
            
            # Get best bid/ask price
            if order_book_orders.bids and len(order_book_orders.bids) > 0:
                bid_price = float(order_book_orders.bids[0].price.replace(".", ""))
            else:
                bid_price = None
            
            if order_book_orders.asks and len(order_book_orders.asks) > 0:
                ask_price = float(order_book_orders.asks[0].price.replace(".", ""))
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
        is_long: bool,
        price_decimals: int
    ) -> int:
        """Calculate stop loss price."""
        if is_long:
            stop_loss_price = avg_entry_price * (1 - self.config.stop_loss_ratio)
        else:
            stop_loss_price = avg_entry_price * (1 + self.config.stop_loss_ratio)
        
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
            
            available_balance = float(account_info.get('available_balance', 0))
            
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
            
            # Calculate position size
            position_size = self.position_service.calculate_position_size(
                available_balance=available_balance,
                reference_position_ratio=reference_position_ratio,
                market_info=market_info,
                current_price=current_price
            )
            
            if position_size is None:
                logger.warning(f"Position size below minimum, skipping trade")
                return {"success": False, "error": "Position size below minimum requirements"}
            
            # Determine order direction
            is_long = trade_type == "long"
            is_ask = not is_long  # is_ask=True means sell (short), is_ask=False means buy (long)
            
            # Convert amounts to integer format
            price_decimals = market_info.get('supported_price_decimals', 6)
            size_decimals = market_info.get('supported_size_decimals', 0)
            
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
                
                # Update stop loss for new position
                if trade_type in ["long", "short"]:
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
            # Find position for this market
            positions = account_info.get('positions', [])
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
                
                # Get updated account info
                updated_account_info = await self.get_account_info(account.index)
                
                # Send notification
                await self.telegram_service.notify_order_closing(
                    account_index=account.index,
                    market_id=market_id,
                    symbol=symbol,
                    base_amount=abs(position_size),
                    quote_amount=abs(position_size) * current_price,
                    price=current_price,
                    position_info=updated_account_info
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
            # Find position for this market
            positions = account_info.get('positions', [])
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
            
            for order_index in existing_orders:
                await self.order_service.cancel_order(
                    signer_client,
                    market_id,
                    order_index
                )
            
            # Calculate stop loss price
            stop_loss_price_int = await self.calculate_stop_loss_price(
                avg_entry_price,
                is_long,
                price_decimals
            )
            
            # Convert position size to integer
            base_amount_int = self.convert_base_amount_to_integer(
                abs(position_size),
                size_decimals
            )
            
            # Create new stop loss order
            await self.order_service.create_stop_loss_order(
                signer_client=signer_client,
                market_id=market_id,
                base_amount=base_amount_int,
                stop_loss_price=stop_loss_price_int,
                is_long=is_long
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

