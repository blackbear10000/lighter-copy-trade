"""
Health monitoring service for Lighter API status.
"""

import lighter
import asyncio
from typing import Optional
from datetime import datetime

from src.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class HealthMonitor:
    """Monitors Lighter API health status."""
    
    def __init__(self):
        self.config = get_config()
        self.api_client: Optional[lighter.ApiClient] = None
        self.is_healthy: bool = True
        self.last_check: Optional[datetime] = None
        self.check_interval: int = 5  # Check every 5 seconds
        self.monitor_task: Optional[asyncio.Task] = None
        self.running: bool = False
    
    async def _get_api_client(self) -> lighter.ApiClient:
        """Get or create API client."""
        if self.api_client is None:
            self.api_client = lighter.ApiClient(
                configuration=lighter.Configuration(host=self.config.base_url)
            )
        return self.api_client
    
    async def check_health(self) -> bool:
        """
        Check API health status.
        
        Returns:
            True if API is healthy (status=1), False otherwise
        """
        try:
            client = await self._get_api_client()
            root_api = lighter.RootApi(client)
            status = await root_api.status()
            
            # Check if status.status == 200 (healthy)
            is_healthy = status.status == 200 if hasattr(status, 'status') else False
            
            self.is_healthy = is_healthy
            self.last_check = datetime.now()
            
            if not is_healthy:
                logger.warning(f"API health check failed: status={status.status if hasattr(status, 'status') else 'unknown'}")
            else:
                logger.debug("API health check passed")
            
            return is_healthy
            
        except Exception as e:
            logger.error(f"Error checking API health: {e}", exc_info=True)
            self.is_healthy = False
            self.last_check = datetime.now()
            return False
    
    async def _monitor_loop(self):
        """Background monitoring loop."""
        logger.info("Starting health monitor")
        self.running = True
        
        while self.running:
            try:
                await self.check_health()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}", exc_info=True)
                await asyncio.sleep(self.check_interval)
        
        logger.info("Health monitor stopped")
    
    def start_monitoring(self):
        """Start background health monitoring."""
        if self.monitor_task is None or self.monitor_task.done():
            self.monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Health monitoring started")
    
    def stop_monitoring(self):
        """Stop background health monitoring."""
        self.running = False
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            logger.info("Health monitoring stopped")
    
    def is_api_healthy(self) -> bool:
        """
        Get current health status.
        
        Returns:
            True if API is healthy, False otherwise
        """
        return self.is_healthy
    
    async def close(self):
        """Close API client connections."""
        self.stop_monitoring()
        if self.api_client:
            await self.api_client.close()
            self.api_client = None


# Global health monitor instance
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get the global health monitor instance."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor

