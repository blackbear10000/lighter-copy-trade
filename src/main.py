"""
Main application entry point for Lighter Copy Trading System.
"""

import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_config
from src.api.routes import router
from src.monitoring.health_check import get_health_monitor
from src.utils.queue_manager import get_queue_manager
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Lighter Copy Trading System")
    
    # Start health monitoring
    health_monitor = get_health_monitor()
    health_monitor.start_monitoring()
    
    # Initial health check
    await health_monitor.check_health()
    
    logger.info("Application started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Lighter Copy Trading System")
    
    # Stop health monitoring
    health_monitor.stop_monitoring()
    await health_monitor.close()
    
    # Shutdown queue manager
    queue_manager = get_queue_manager()
    await queue_manager.shutdown()
    
    logger.info("Application shut down complete")


# Create FastAPI application
app = FastAPI(
    title="Lighter Copy Trading System",
    description="HTTP API for executing trades on Lighter platform",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Lighter Copy Trading System",
        "version": "1.0.0",
        "status": "running"
    }


if __name__ == "__main__":
    # Load configuration to validate on startup
    try:
        config = get_config()
        logger.info(f"Configuration loaded: {len(config.accounts)} accounts configured")
    except Exception as e:
        logger.error(f"Configuration error: {e}", exc_info=True)
        raise
    
    # Run the application
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )

