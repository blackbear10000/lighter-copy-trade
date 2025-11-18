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


def escape_markdown(text: str, for_code_block: bool = False) -> str:
    """
    Escape special Markdown characters, but preserve numbers and common formatting.
    
    Args:
        text: Text to escape
        for_code_block: If True, only escape backticks (for use inside code blocks)
        
    Returns:
        Escaped text
    """
    text = str(text)
    
    if for_code_block:
        # Inside code blocks, only backticks need escaping
        return text.replace('`', '\\`')
    
    # For regular text, escape characters that can break Markdown parsing
    # Don't escape: . (dots in numbers), - (hyphens), ( ) (parentheses), +, = (in formulas)
    # Escape only: _, *, [, ], ~, `, >, #, |, {, }, !
    # Note: We don't escape + and = as they're commonly used in formulas and numbers
    special_chars = ['_', '*', '[', ']', '~', '`', '>', '#', '|', '{', '}', '!']
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
        self.top_separator = "╔════════════════════════════════════╗"
    
    def _prepend_separator(self, message: str) -> str:
        """Add a bold separator at the top of every message for visual isolation."""
        return f"{self.top_separator}\n{message}"
    
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
        
        message = f"*📈 Order Opened*\n"
        message += f"━━━━━━━━━━━━━━━━━━━━\n"
        message += f"*Time:* `{timestamp}`\n"
        message += f"*Account:* `{str(account_index)}`\n"
        message += f"*Market:* `{escape_markdown(symbol, for_code_block=True)}` (ID: `{market_id}`)\n"
        message += f"*Type:* `{trade_type.upper()}`\n"
        message += f"*Amount:* `{base_amount:.6f}` {escape_markdown(symbol)}\n"
        message += f"*Value:* `${quote_amount:.2f}`\n"
        message += f"*Price:* `${price:.6f}`\n"
        
        if position_info:
            message += f"\n*💼 Current Positions*\n"
            message += f"━━━━━━━━━━━━━━━━━━━━\n"
            accounts = position_info.get('accounts', [])
            if accounts and len(accounts) > 0:
                positions = accounts[0].get('positions', [])
                if positions:
                    total_value = 0.0
                    total_pnl = 0.0
                    
                    for pos in positions:
                        pos_symbol_raw = str(pos.get('symbol', 'N/A'))
                        pos_symbol = escape_markdown(pos_symbol_raw)
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
                        
                        # Determine position direction indicator
                        direction_indicator = "📈" if sign == 1 else "📉"
                        if sign not in (-1, 1):
                            if pos_size > 0:
                                sign = 1
                                direction_indicator = "📈"
                            elif pos_size < 0:
                                sign = -1
                                direction_indicator = "📉"
                        direction_label = "LONG" if sign == 1 else "SHORT"
                        
                        # Format position line with better structure
                        pnl_sign = "+" if pnl >= 0 else ""
                        pnl_pct_sign = "+" if pnl_pct >= 0 else ""
                        pnl_color = "🟢" if pnl >= 0 else "🔴"
                        
                        message += f"\n{direction_indicator} *{pos_symbol}*\n"
                        message += f"  Size: `{abs(pos_size):.6f}` {pos_symbol_raw}\n"
                        message += f"  Value: `${pos_value:.2f}`\n"
                        message += f"  Entry: `${avg_entry_price:.6f}`\n"
                        message += f"  Direction: `{direction_label}`\n"
                        message += f"  PnL: {pnl_color} {pnl_sign}${pnl:.2f} ({pnl_pct_sign}{pnl_pct:.2f}%)\n"
                        message += f"  Leverage: `{leverage_str}`\n"
                        message += f"  Stop Loss: `{stop_loss_str}`\n"
                    
                    # Add total value and PnL summary
                    total_pnl_sign = "+" if total_pnl >= 0 else ""
                    total_pnl_color = "🟢" if total_pnl >= 0 else "🔴"
                    message += f"\n*📊 Summary*\n"
                    message += f"━━━━━━━━━━━━━━━━━━━━\n"
                    message += f"*Total Value:* `${total_value:.2f}`\n"
                    message += f"*Total PnL:* {total_pnl_color} {total_pnl_sign}${total_pnl:.2f}\n"
                    
                    # Add account total assets and leverage
                    account_data = accounts[0]
                    total_asset_value = float(account_data.get('total_asset_value', '0'))
                    available_balance_value = float(account_data.get('available_balance', '0'))
                    
                    # Calculate leverage ratio: Total Value (positions) / Account Total Assets
                    leverage_ratio = 0.0
                    if total_asset_value > 0:
                        leverage_ratio = total_value / total_asset_value
                    
                    message += f"*Account Assets:* `${total_asset_value:.2f}`\n"
                    message += f"*Available Balance:* `${available_balance_value:.2f}`\n"
                    message += f"*Leverage Ratio:* `{leverage_ratio:.2f}x`\n"
                else:
                    message += f"*No open positions*\n"
                    
                    # Even with no positions, show account info
                    account_data = accounts[0]
                    total_asset_value = float(account_data.get('total_asset_value', '0'))
                    available_balance_value = float(account_data.get('available_balance', '0'))
                    
                    # No positions, leverage ratio is 0
                    leverage_ratio = 0.0
                    
                    message += f"\n*📊 Account Summary*\n"
                    message += f"━━━━━━━━━━━━━━━━━━━━\n"
                    message += f"*Account Assets:* `${total_asset_value:.2f}`\n"
                    message += f"*Available Balance:* `${available_balance_value:.2f}`\n"
                    message += f"*Leverage Ratio:* `{leverage_ratio:.2f}x`\n"
            else:
                message += f"*No open positions*\n"
        
        return self._prepend_separator(message)
    
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
        
        message = f"*📉 Order Closed/Reduced*\n"
        message += f"━━━━━━━━━━━━━━━━━━━━\n"
        message += f"*Time:* `{timestamp}`\n"
        message += f"*Account:* `{str(account_index)}`\n"
        message += f"*Market:* `{escape_markdown(symbol, for_code_block=True)}` (ID: `{market_id}`)\n"
        message += f"*Amount:* `{base_amount:.6f}` {escape_markdown(symbol)}\n"
        message += f"*Value:* `${quote_amount:.2f}`\n"
        message += f"*Price:* `${price:.6f}`\n"
        
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
                        
                        # Color indicators
                        total_color = "🟢" if total_pnl >= 0 else "🔴"
                        close_color = "🟢" if realized_pnl_from_close >= 0 else "🔴"
                        realized_color = "🟢" if realized_pnl >= 0 else "🔴"
                        unrealized_color = "🟢" if unrealized_pnl >= 0 else "🔴"
                        
                        message += f"\n*💰 Profit/Loss*\n"
                        message += f"━━━━━━━━━━━━━━━━━━━━\n"
                        if realized_pnl_from_close != 0:
                            message += f"*This Close:* {close_color} {close_sign}${realized_pnl_from_close:.2f}\n"
                        message += f"*Realized PnL:* {realized_color} {realized_sign}${realized_pnl:.2f}\n"
                        message += f"*Unrealized PnL:* {unrealized_color} {unrealized_sign}${unrealized_pnl:.2f}\n"
                        message += f"*Total PnL:* {total_color} {pnl_sign}${total_pnl:.2f}\n"
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
                                    close_color = "🟢" if realized_pnl_from_close >= 0 else "🔴"
                                    message += f"\n*💰 Profit/Loss (Closed Position)*\n"
                                    message += f"━━━━━━━━━━━━━━━━━━━━\n"
                                    message += f"*This Close:* {close_color} {close_sign}${realized_pnl_from_close:.2f}\n"
                                    break
        
        return self._prepend_separator(message)
    
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
        
        message = f"*⚠️ Error Alert*\n"
        message += f"━━━━━━━━━━━━━━━━━━━━\n"
        message += f"*Time:* `{timestamp}`\n"
        message += f"*Type:* `{escape_markdown(error_type, for_code_block=True)}`\n"
        message += f"*Message:*\n`{escape_markdown(error_message, for_code_block=True)}`\n"
        
        if context:
            message += f"\n*📋 Context*\n"
            message += f"━━━━━━━━━━━━━━━━━━━━\n"
            for key, value in context.items():
                # For code blocks, only escape backticks
                key_text = escape_markdown(str(key), for_code_block=True)
                escaped_value = str(value)
                # Truncate very long values for readability
                if len(escaped_value) > 100:
                    escaped_value = escaped_value[:97] + "..."
                escaped_value = escape_markdown(escaped_value, for_code_block=True)
                message += f"`{key_text}`: `{escaped_value}`\n"
        
        return self._prepend_separator(message)
    
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

