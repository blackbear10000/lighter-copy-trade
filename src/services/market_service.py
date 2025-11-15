"""
Market information service for querying market data and symbol resolution.
"""

import lighter
from typing import Dict, Optional, List
from datetime import datetime, timedelta

from src.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class MarketService:
    """Service for market information queries."""
    
    def __init__(self):
        self.config = get_config()
        self.api_client: Optional[lighter.ApiClient] = None
        self.order_books_cache: Optional[List[Dict]] = None
        self.cache_timestamp: Optional[datetime] = None
        self.cache_ttl = timedelta(minutes=5)  # Cache for 5 minutes
        self.symbol_to_market_id: Dict[str, int] = {}
    
    async def _get_api_client(self) -> lighter.ApiClient:
        """Get or create API client."""
        if self.api_client is None:
            self.api_client = lighter.ApiClient(
                configuration=lighter.Configuration(host=self.config.base_url)
            )
        return self.api_client
    
    async def _refresh_order_books(self) -> List[Dict]:
        """Refresh order books from API."""
        try:
            client = await self._get_api_client()
            order_api = lighter.OrderApi(client)
            result = await order_api.order_books()
            
            # Convert to dict format
            if hasattr(result, 'to_dict'):
                data = result.to_dict()
            else:
                data = result
            
            order_books = data.get('order_books', [])
            self.order_books_cache = order_books
            self.cache_timestamp = datetime.now()
            
            # Build symbol to market_id mapping
            self.symbol_to_market_id = {}
            for book in order_books:
                if book.get('status') == 'active':
                    symbol = book.get('symbol')
                    market_id = book.get('market_id')
                    if symbol and market_id is not None:
                        self.symbol_to_market_id[symbol] = market_id
            
            logger.info(f"Refreshed order books cache: {len(order_books)} markets")
            return order_books
            
        except Exception as e:
            logger.error(f"Error refreshing order books: {e}", exc_info=True)
            raise
    
    async def get_order_books(self, force_refresh: bool = False) -> List[Dict]:
        """
        Get order books, using cache if available.
        
        Args:
            force_refresh: Force refresh of cache
            
        Returns:
            List of order book dictionaries
        """
        now = datetime.now()
        
        if (force_refresh or 
            self.order_books_cache is None or 
            self.cache_timestamp is None or
            (now - self.cache_timestamp) > self.cache_ttl):
            await self._refresh_order_books()
        
        return self.order_books_cache
    
    async def resolve_symbol_to_market_id(self, symbol: str) -> Optional[int]:
        """
        Resolve symbol to market_id.
        
        Args:
            symbol: Trading pair symbol (e.g., "ETH", "BTC", "RESOLV")
            
        Returns:
            Market ID if found, None otherwise
        """
        # Refresh cache if needed
        await self.get_order_books()
        
        # Check cache first
        market_id = self.symbol_to_market_id.get(symbol.upper())
        if market_id is not None:
            return market_id
        
        # If not in cache, refresh and try again
        await self._refresh_order_books()
        return self.symbol_to_market_id.get(symbol.upper())
    
    async def get_market_info(self, market_id: int) -> Optional[Dict]:
        """
        Get market information by market_id.
        
        Args:
            market_id: Market ID
            
        Returns:
            Market information dictionary or None if not found
        """
        order_books = await self.get_order_books()
        
        for book in order_books:
            if book.get('market_id') == market_id:
                return book
        
        return None
    
    async def validate_market(self, market_id: Optional[int] = None, symbol: Optional[str] = None) -> Dict:
        """
        Validate market and return market_id.
        
        Args:
            market_id: Market ID (optional)
            symbol: Symbol (optional)
            
        Returns:
            Dictionary with 'market_id' and 'market_info'
            
        Raises:
            ValueError: If market is invalid or not found
        """
        if market_id is not None:
            # Validate by market_id
            market_info = await self.get_market_info(market_id)
            if market_info is None:
                raise ValueError(f"Market ID {market_id} not found")
            if market_info.get('status') != 'active':
                raise ValueError(f"Market ID {market_id} is not active")
            return {
                'market_id': market_id,
                'market_info': market_info
            }
        
        elif symbol is not None:
            # Resolve symbol to market_id
            resolved_market_id = await self.resolve_symbol_to_market_id(symbol)
            if resolved_market_id is None:
                raise ValueError(f"Symbol '{symbol}' not found or not active")
            
            market_info = await self.get_market_info(resolved_market_id)
            return {
                'market_id': resolved_market_id,
                'market_info': market_info
            }
        
        else:
            raise ValueError("Either market_id or symbol must be provided")
    
    async def close(self):
        """Close API client connections."""
        if self.api_client:
            await self.api_client.close()
            self.api_client = None


# Global market service instance
_market_service: Optional[MarketService] = None


def get_market_service() -> MarketService:
    """Get the global market service instance."""
    global _market_service
    if _market_service is None:
        _market_service = MarketService()
    return _market_service

