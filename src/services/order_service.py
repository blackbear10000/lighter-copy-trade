"""
Order execution service.
"""

import lighter
from typing import Dict, Optional, Tuple
from collections import defaultdict
import asyncio

from src.config import get_config, AccountConfig
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class OrderService:
    """Service for order execution."""
    
    def __init__(self):
        self.config = get_config()
        # In-memory counter for client_order_index per account
        # In production, you might want to query actual max from API
        self.client_order_index_counters: Dict[int, int] = defaultdict(int)
    
    async def get_client_order_index(
        self,
        signer_client: lighter.SignerClient,
        account_index: int
    ) -> int:
        """
        Get next client order index.
        
        Uses an in-memory counter per account. For a production system,
        you might want to query the API to find the actual max client_order_index.
        
        Args:
            signer_client: Signer client instance
            account_index: Account index
            
        Returns:
            Next client order index
        """
        # Increment and return counter for this account
        self.client_order_index_counters[account_index] += 1
        return self.client_order_index_counters[account_index]
    
    async def create_signer_client(self, account: AccountConfig) -> lighter.SignerClient:
        """
        Create a signer client for the account.
        
        Args:
            account: Account configuration
            
        Returns:
            Signer client instance
        """
        return lighter.SignerClient(
            url=self.config.base_url,
            private_key=account.private_key,
            account_index=account.index,
            api_key_index=account.api_index,
        )
    
    async def execute_market_order(
        self,
        signer_client: lighter.SignerClient,
        market_id: int,
        base_amount: int,
        is_ask: bool,
        max_slippage: Optional[float] = None
    ) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        """
        Execute a market order with slippage control.
        
        Args:
            signer_client: Signer client instance
            market_id: Market ID
            base_amount: Base amount (in integer format with precision)
            is_ask: True for sell, False for buy
            max_slippage: Maximum slippage (uses config default if None)
            
        Returns:
            Tuple of (order, tx_hash, error)
        """
        if max_slippage is None:
            max_slippage = self.config.max_slippage
        
        try:
            # Get client order index
            client_order_index = await self.get_client_order_index(
                signer_client,
                signer_client.account_index
            )
            
            # Execute market order with slippage control
            order, tx_hash, error = await signer_client.create_market_order_limited_slippage(
                market_index=market_id,
                client_order_index=client_order_index,
                base_amount=base_amount,
                max_slippage=max_slippage,
                is_ask=is_ask,
            )
            
            if error:
                logger.error(f"Market order error: {error}")
                return None, None, error
            
            logger.info(f"Market order executed: tx_hash={tx_hash}")
            return order, tx_hash, None
            
        except Exception as e:
            logger.error(f"Error executing market order: {e}", exc_info=True)
            return None, None, str(e)
    
    async def get_existing_stop_loss_orders(
        self,
        signer_client: lighter.SignerClient,
        market_id: int
    ) -> list:
        """
        Get existing stop loss orders for a market.
        
        Note: This is a placeholder. You may need to query orders through the API
        to find existing stop loss orders.
        
        Args:
            signer_client: Signer client instance
            market_id: Market ID
            
        Returns:
            List of order indices to cancel
        """
        # TODO: Implement actual query for stop loss orders
        # This would require querying account orders and filtering for stop loss type
        return []
    
    async def create_stop_loss_order(
        self,
        signer_client: lighter.SignerClient,
        market_id: int,
        base_amount: int,
        stop_loss_price: int,
        is_long: bool
    ) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        """
        Create a stop loss order.
        
        Args:
            signer_client: Signer client instance
            market_id: Market ID
            base_amount: Base amount (in integer format with precision)
            stop_loss_price: Stop loss price (in integer format with precision)
            is_long: True for long position, False for short
            
        Returns:
            Tuple of (order, tx_hash, error)
        """
        try:
            # Get client order index
            client_order_index = await self.get_client_order_index(
                signer_client,
                signer_client.account_index
            )
            
            # For long positions, stop loss is a sell order (is_ask=True)
            # For short positions, stop loss is a buy order (is_ask=False)
            is_ask = is_long
            
            # Create stop loss order
            order, tx_hash, error = await signer_client.create_sl_order(
                market_index=market_id,
                client_order_index=client_order_index,
                base_amount=base_amount,
                trigger_price=stop_loss_price,
                price=stop_loss_price,
                is_ask=is_ask,
                reduce_only=True,
            )
            
            if error:
                logger.error(f"Stop loss order error: {error}")
                return None, None, error
            
            logger.info(f"Stop loss order created: tx_hash={tx_hash}")
            return order, tx_hash, None
            
        except Exception as e:
            logger.error(f"Error creating stop loss order: {e}", exc_info=True)
            return None, None, str(e)
    
    async def cancel_order(
        self,
        signer_client: lighter.SignerClient,
        market_id: int,
        order_index: int
    ) -> Tuple[Optional[Dict], Optional[str], Optional[str]]:
        """
        Cancel an order.
        
        Args:
            signer_client: Signer client instance
            market_id: Market ID
            order_index: Order index to cancel
            
        Returns:
            Tuple of (cancel_order, tx_hash, error)
        """
        try:
            cancel_order, tx_hash, error = await signer_client.cancel_order(
                market_index=market_id,
                order_index=order_index,
            )
            
            if error:
                logger.error(f"Cancel order error: {error}")
                return None, None, error
            
            logger.info(f"Order cancelled: order_index={order_index}, tx_hash={tx_hash}")
            return cancel_order, tx_hash, None
            
        except Exception as e:
            logger.error(f"Error cancelling order: {e}", exc_info=True)
            return None, None, str(e)

