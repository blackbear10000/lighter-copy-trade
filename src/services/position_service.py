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
        total_assets: float,
        available_balance: float,
        reference_position_ratio: float,
        market_info: Dict,
        current_price: float
    ) -> Optional[Dict[str, float]]:
        """
        Calculate position size based on total assets, ratio, and scaling factor.
        
        Args:
            total_assets: Total asset value in quote currency (USDC)
            available_balance: Available balance in quote currency (USDC) - used for validation
            reference_position_ratio: Reference position ratio (0-1)
            market_info: Market information dictionary
            current_price: Current market price
            
        Returns:
            Dictionary with 'base_amount', 'quote_amount', and 'insufficient_balance' flag,
            or None if below minimum
        """
        # Get minimum requirements
        min_base_amount = float(market_info.get('min_base_amount', 0))
        min_quote_amount = float(market_info.get('min_quote_amount', 0))
        
        # Calculate quote amount: total_assets * ratio * scaling_factor
        quote_amount = total_assets * reference_position_ratio * self.config.scaling_factor
        
        # Check if available balance is sufficient
        insufficient_balance = quote_amount > available_balance
        
        # Log calculation details
        logger.debug(
            f"Position size calculation: total_assets={total_assets}, "
            f"available_balance={available_balance}, ratio={reference_position_ratio}, "
            f"scaling_factor={self.config.scaling_factor}, calculated_quote_amount={quote_amount}, "
            f"min_quote_amount={min_quote_amount}, insufficient_balance={insufficient_balance}"
        )
        
        # Warn if insufficient balance
        if insufficient_balance:
            logger.warning(
                f"Insufficient available balance: required={quote_amount:.6f}, "
                f"available={available_balance:.6f}, shortfall={quote_amount - available_balance:.6f}"
            )
        
        # First check: quote amount must meet minimum requirement
        if quote_amount < min_quote_amount:
            logger.warning(
                f"Quote amount below minimum: calculated={quote_amount:.6f} < min={min_quote_amount:.6f}. "
                f"Required minimum quote amount: {min_quote_amount:.6f}, "
                f"but calculated amount (balance={available_balance:.6f} * ratio={reference_position_ratio} * "
                f"scaling={self.config.scaling_factor}) = {quote_amount:.6f}"
            )
            return None
        
        # Convert to base amount
        if current_price <= 0:
            logger.error(f"Invalid current price: {current_price}")
            return None
        
        base_amount = quote_amount / current_price
        
        # Get precision
        size_decimals = market_info.get('supported_size_decimals', 0)
        
        # Round base amount to required precision
        if size_decimals >= 0:
            precision = Decimal(10) ** -size_decimals
            base_amount = float(Decimal(str(base_amount)).quantize(precision, rounding=ROUND_DOWN))
        
        # Second check: base amount must meet minimum requirement
        if base_amount < min_base_amount:
            logger.warning(
                f"Base amount below minimum: calculated={base_amount:.6f} < min={min_base_amount:.6f}. "
                f"Quote amount={quote_amount:.6f} is sufficient, but base amount "
                f"(quote={quote_amount:.6f} / price={current_price:.6f}) = {base_amount:.6f} is too small"
            )
            return None
        
        logger.debug(
            f"Position size calculated successfully: base={base_amount:.6f}, quote={quote_amount:.6f}, "
            f"insufficient_balance={insufficient_balance}"
        )
        
        return {
            'base_amount': base_amount,
            'quote_amount': quote_amount,
            'insufficient_balance': insufficient_balance
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

