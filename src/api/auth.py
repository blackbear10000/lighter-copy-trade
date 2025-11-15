"""
API authentication middleware.
"""

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from typing import Optional

from src.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> bool:
    """
    Verify API key from header.
    
    Args:
        api_key: API key from header
        
    Returns:
        True if valid, raises HTTPException otherwise
    """
    config = get_config()
    
    # If no API key is configured, allow all requests (for development)
    if not config.api_key:
        logger.warning("No API_KEY configured, allowing all requests")
        return True
    
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="API key required"
        )
    
    if api_key != config.api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )
    
    return True

