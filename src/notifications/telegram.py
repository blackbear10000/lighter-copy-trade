"""
Telegram notification service.
"""

import aiohttp
import re
from typing import Dict, Optional, Any
from datetime import datetime

from src.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def escape_markdown(text: str) -> str:
    """
    Escape special Markdown characters, but preserve numbers and common formatting.
    
    Args:
        text: Text to escape
        
    Returns:
        Escaped text
    """
    text = str(text)
    # Only escape Markdown special characters that can cause parsing errors
    # Don't escape: . (dots in numbers are fine), - (hyphens are fine), ( ) (parentheses are fine in most contexts)
    # Escape: _, *, [, ], ~, `, >, #, +, =, |, {, }, !
    special_chars = ['_', '*', '[', ']', '~', '`', '>', '#', '+', '=', '|', '{', '}', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


class TelegramService:
    """Service for sending Telegram notifications."""
    
    def __init__(self):
        self.config = get_config()
        self.base_url = f"https://api.telegram.org/bot{self.config.telegram_bot_api_key}"
        self.chat_id = self.config.telegram_group_id
        self.thread_id = self.config.telegram_thread_id
    
    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a message to Telegram.
        
        Args:
            text: Message text
            parse_mode: Parse mode (Markdown or HTML)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            
            # Add message_thread_id if configured (for forum groups)
            if self.thread_id is not None:
                payload["message_thread_id"] = self.thread_id
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.debug("Telegram message sent successfully")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(f"Telegram API error: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}", exc_info=True)
            return False
    
    def format_order_opening_message(
        self,
        account_index: int,
        market_id: int,
        symbol: str,
        trade_type: str,
        base_amount: float,
        quote_amount: float,
        price: float,
        position_info: Optional[Dict] = None
    ) -> str:
        """
        Format order opening notification message.
        
        Args:
            account_index: Account index
            market_id: Market ID
            symbol: Trading symbol
            trade_type: Trade type (long/short)
            base_amount: Base amount
            quote_amount: Quote amount
            price: Execution price
            position_info: Current position information
            
        Returns:
            Formatted message
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"*Order Opened*\n"
        message += f"Time: {timestamp}\n"
        message += f"Account: {escape_markdown(str(account_index))}\n"
        message += f"Market: {escape_markdown(symbol)} (ID: {market_id})\n"
        message += f"Type: {trade_type.upper()}\n"
        message += f"Amount: {base_amount:.6f} {escape_markdown(symbol)}\n"
        message += f"Value: ${quote_amount:.2f}\n"
        message += f"Price: ${price:.6f}\n"
        
        if position_info:
            message += f"\n*Current Positions:*\n"
            accounts = position_info.get('accounts', [])
            if accounts and len(accounts) > 0:
                positions = accounts[0].get('positions', [])
                if positions:
                    total_value = 0.0
                    total_pnl = 0.0
                    
                    for pos in positions:
                        pos_symbol = escape_markdown(str(pos.get('symbol', 'N/A')))
                        pos_size = float(pos.get('position', '0'))
                        pos_value = float(pos.get('position_value', '0'))
                        pnl = float(pos.get('unrealized_pnl', '0'))
                        avg_entry_price = float(pos.get('avg_entry_price', '0'))
                        sign = pos.get('sign', 1)  # 1 for long, -1 for short
                        
                        # Accumulate total value and PnL
                        total_value += pos_value
                        total_pnl += pnl
                        
                        # Calculate current price from position value and size
                        current_price = 0.0
                        if abs(pos_size) > 0:
                            current_price = pos_value / abs(pos_size)
                        
                        # Calculate PnL percentage
                        pnl_pct = 0.0
                        if avg_entry_price > 0:
                            if sign == 1:  # Long position
                                pnl_pct = ((current_price - avg_entry_price) / avg_entry_price) * 100
                            else:  # Short position
                                pnl_pct = ((avg_entry_price - current_price) / avg_entry_price) * 100
                        
                        # Calculate stop loss price using formula: avg_entry_price * (1 - initial_margin_fraction * STOP_LOSS_RATIO)
                        stop_loss_price = 0.0
                        stop_loss_str = "N/A"
                        if avg_entry_price > 0:
                            initial_margin_fraction = float(pos.get('initial_margin_fraction', 0))
                            margin_fraction = initial_margin_fraction / 100.0 if initial_margin_fraction > 0 else 0.3333
                            
                            if sign == 1:  # Long position
                                stop_loss_price = avg_entry_price * (1 - margin_fraction * self.config.stop_loss_ratio)
                            else:  # Short position
                                stop_loss_price = avg_entry_price * (1 + margin_fraction * self.config.stop_loss_ratio)
                            
                            stop_loss_str = f"${stop_loss_price:.6f}"
                        
                        # Calculate leverage for this position
                        leverage = 0.0
                        leverage_str = "N/A"
                        allocated_margin = float(pos.get('allocated_margin', 0))
                        initial_margin_fraction = float(pos.get('initial_margin_fraction', 0))
                        
                        if allocated_margin > 0:
                            # Isolated margin: leverage = position_value / allocated_margin
                            leverage = pos_value / allocated_margin if allocated_margin > 0 else 0
                        else:
                            # Cross margin: leverage = 1 / margin_fraction
                            margin_fraction = initial_margin_fraction / 100.0 if initial_margin_fraction > 0 else 0.3333
                            leverage = 1.0 / margin_fraction if margin_fraction > 0 else 0
                        
                        # Format leverage as "SYMBOL xN" format
                        if leverage > 0:
                            leverage_int = int(round(leverage))
                            leverage_str = f"{pos_symbol} x{leverage_int}"
                        else:
                            leverage_str = "N/A"
                        
                        # Format position line with all information
                        pnl_sign = "+" if pnl >= 0 else ""
                        pnl_pct_sign = "+" if pnl_pct >= 0 else ""
                        message += (
                            f"- {pos_symbol}: {abs(pos_size):.6f} "
                            f"(Value: ${pos_value:.2f}, "
                            f"Entry: ${avg_entry_price:.6f}, "
                            f"PnL: {pnl_sign}${pnl:.2f} ({pnl_pct_sign}{pnl_pct:.2f}%), "
                            f"{leverage_str}, "
                            f"Stop Loss: {stop_loss_str})\n"
                        )
                    
                    # Add total value and PnL summary
                    total_pnl_sign = "+" if total_pnl >= 0 else ""
                    message += f"\n*Total Value:* ${total_value:.2f} (PnL: {total_pnl_sign}${total_pnl:.2f})\n"
                    
                    # Add account total assets and leverage
                    account_data = accounts[0]
                    total_asset_value = float(account_data.get('total_asset_value', '0'))
                    
                    # Calculate leverage ratio: Total Value (positions) / Account Total Assets
                    leverage_ratio = 0.0
                    if total_asset_value > 0:
                        leverage_ratio = total_value / total_asset_value
                    
                    message += f"*Account Total Assets:* ${total_asset_value:.2f}\n"
                    message += f"*Leverage Ratio:* {leverage_ratio:.2f}x\n"
                else:
                    message += "No open positions\n"
                    
                    # Even with no positions, show account info
                    account_data = accounts[0]
                    total_asset_value = float(account_data.get('total_asset_value', '0'))
                    
                    # No positions, leverage ratio is 0
                    leverage_ratio = 0.0
                    
                    message += f"\n*Account Total Assets:* ${total_asset_value:.2f}\n"
                    message += f"*Leverage Ratio:* {leverage_ratio:.2f}x\n"
            else:
                message += "No open positions\n"
        
        return message
    
    def format_order_closing_message(
        self,
        account_index: int,
        market_id: int,
        symbol: str,
        base_amount: float,
        quote_amount: float,
        price: float,
        position_info: Optional[Dict] = None
    ) -> str:
        """
        Format order closing/reducing notification message.
        
        Args:
            account_index: Account index
            market_id: Market ID
            symbol: Trading symbol
            base_amount: Base amount
            quote_amount: Quote amount
            price: Execution price
            position_info: Position information with PnL
            
        Returns:
            Formatted message
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"*Order Closed/Reduced*\n"
        message += f"Time: {timestamp}\n"
        message += f"Account: {escape_markdown(str(account_index))}\n"
        message += f"Market: {escape_markdown(symbol)} (ID: {market_id})\n"
        message += f"Amount: {base_amount:.6f} {escape_markdown(symbol)}\n"
        message += f"Value: ${quote_amount:.2f}\n"
        message += f"Price: ${price:.6f}\n"
        
        if position_info:
            accounts = position_info.get('accounts', [])
            if accounts and len(accounts) > 0:
                positions = accounts[0].get('positions', [])
                position_found = False
                
                for pos in positions:
                    if pos.get('market_id') == market_id:
                        position_found = True
                        unrealized_pnl = float(pos.get('unrealized_pnl', 0))
                        realized_pnl = float(pos.get('realized_pnl', 0))
                        
                        # Get PnL from this close operation if available
                        realized_pnl_from_close = float(pos.get('realized_pnl_from_close', 0))
                        if realized_pnl_from_close == 0:
                            # Calculate from before/after if not provided
                            realized_pnl_before = float(pos.get('realized_pnl_before', 0))
                            realized_pnl_from_close = realized_pnl - realized_pnl_before
                        
                        # Calculate PnL details
                        total_pnl = unrealized_pnl + realized_pnl
                        pnl_sign = "+" if total_pnl >= 0 else ""
                        unrealized_sign = "+" if unrealized_pnl >= 0 else ""
                        realized_sign = "+" if realized_pnl >= 0 else ""
                        close_sign = "+" if realized_pnl_from_close >= 0 else ""
                        
                        message += f"\n*Profit/Loss:*\n"
                        if realized_pnl_from_close != 0:
                            message += f"PnL from this close: {close_sign}${realized_pnl_from_close:.2f}\n"
                        message += f"Total Realized PnL: {realized_sign}${realized_pnl:.2f}\n"
                        message += f"Unrealized PnL: {unrealized_sign}${unrealized_pnl:.2f}\n"
                        message += f"Total PnL: {pnl_sign}${total_pnl:.2f}\n"
                        break
                
                # If position was fully closed, show realized PnL from close operation
                if not position_found:
                    # Try to get from the first position in the list (might be the closed one)
                    if positions and len(positions) > 0:
                        # Check if we have the closed position data in position_info
                        for pos in positions:
                            if 'realized_pnl_from_close' in pos:
                                realized_pnl_from_close = float(pos.get('realized_pnl_from_close', 0))
                                if realized_pnl_from_close != 0:
                                    close_sign = "+" if realized_pnl_from_close >= 0 else ""
                                    message += f"\n*Profit/Loss (Closed Position):*\n"
                                    message += f"PnL from this close: {close_sign}${realized_pnl_from_close:.2f}\n"
                                    break
        
        return message
    
    def format_error_message(
        self,
        error_type: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format error notification message.
        
        Args:
            error_type: Type of error
            error_message: Error message
            context: Additional context
            
        Returns:
            Formatted message
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"*Error Alert*\n"
        message += f"Time: {timestamp}\n"
        message += f"Type: {error_type}\n"
        message += f"Message: {error_message}\n"
        
        if context:
            message += f"\n*Context:*\n"
            for key, value in context.items():
                # Escape values to prevent Markdown parsing errors
                # Keys are usually safe, but escape them too to be safe
                escaped_key = escape_markdown(str(key))
                escaped_value = escape_markdown(str(value))
                message += f"{escaped_key}: {escaped_value}\n"
        
        return message
    
    async def notify_order_opening(
        self,
        account_index: int,
        market_id: int,
        symbol: str,
        trade_type: str,
        base_amount: float,
        quote_amount: float,
        price: float,
        position_info: Optional[Dict] = None
    ):
        """Send order opening notification."""
        message = self.format_order_opening_message(
            account_index, market_id, symbol, trade_type,
            base_amount, quote_amount, price, position_info
        )
        await self.send_message(message)
    
    async def notify_order_closing(
        self,
        account_index: int,
        market_id: int,
        symbol: str,
        base_amount: float,
        quote_amount: float,
        price: float,
        position_info: Optional[Dict] = None
    ):
        """Send order closing notification."""
        message = self.format_order_closing_message(
            account_index, market_id, symbol,
            base_amount, quote_amount, price, position_info
        )
        await self.send_message(message)
    
    async def notify_error(
        self,
        error_type: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None
    ):
        """Send error notification."""
        message = self.format_error_message(error_type, error_message, context)
        await self.send_message(message)


# Global Telegram service instance
_telegram_service: Optional[TelegramService] = None


def get_telegram_service() -> TelegramService:
    """Get the global Telegram service instance."""
    global _telegram_service
    if _telegram_service is None:
        _telegram_service = TelegramService()
    return _telegram_service

