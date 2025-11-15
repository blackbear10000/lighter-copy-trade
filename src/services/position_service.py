"""
Position calculation service.
"""

from decimal import Decimal, ROUND_DOWN
from typing import Dict, Optional

from src.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class PositionService:
    """Service for position size calculations."""
    
    def __init__(self):
        self.config = get_config()
    
    def calculate_position_size(
        self,
        available_balance: float,
        reference_position_ratio: float,
        market_info: Dict,
        current_price: float
    ) -> Optional[Dict[str, float]]:
        """
        Calculate position size based on available balance, ratio, and scaling factor.
        
        Args:
            available_balance: Available balance in quote currency (USDC)
            reference_position_ratio: Reference position ratio (0-1)
            market_info: Market information dictionary
            current_price: Current market price
            
        Returns:
            Dictionary with 'base_amount' and 'quote_amount', or None if below minimum
        """
        # Calculate quote amount: balance * ratio * scaling_factor
        quote_amount = available_balance * reference_position_ratio * self.config.scaling_factor
        
        # Convert to base amount
        base_amount = quote_amount / current_price if current_price > 0 else 0
        
        # Get minimum requirements
        min_base_amount = float(market_info.get('min_base_amount', 0))
        min_quote_amount = float(market_info.get('min_quote_amount', 0))
        
        # Get precision
        size_decimals = market_info.get('supported_size_decimals', 0)
        
        # Round base amount to required precision
        if size_decimals >= 0:
            precision = Decimal(10) ** -size_decimals
            base_amount = float(Decimal(str(base_amount)).quantize(precision, rounding=ROUND_DOWN))
        
        # Validate minimum amounts
        if base_amount < min_base_amount or quote_amount < min_quote_amount:
            logger.warning(
                f"Calculated amount below minimum: base={base_amount} (min={min_base_amount}), "
                f"quote={quote_amount} (min={min_quote_amount})"
            )
            return None
        
        return {
            'base_amount': base_amount,
            'quote_amount': quote_amount
        }
    
    def format_amount(self, amount: float, decimals: int) -> float:
        """
        Format amount to required decimal places.
        
        Args:
            amount: Amount to format
            decimals: Number of decimal places
            
        Returns:
            Formatted amount
        """
        if decimals < 0:
            return amount
        
        precision = Decimal(10) ** -decimals
        return float(Decimal(str(amount)).quantize(precision, rounding=ROUND_DOWN))

