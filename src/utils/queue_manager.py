"""
Request queue management for handling concurrent requests.
"""

import asyncio
from typing import Dict, Any, Callable, Awaitable
from collections import defaultdict
import uuid
from datetime import datetime

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class QueueManager:
    """Manages request queues per account."""
    
    def __init__(self):
        self.queues: Dict[int, asyncio.Queue] = defaultdict(asyncio.Queue)
        self.workers: Dict[int, asyncio.Task] = {}
        self.running = True
    
    async def enqueue(
        self,
        account_index: int,
        request_data: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
    ) -> str:
        """
        Enqueue a request for processing.
        
        Args:
            account_index: Account index for the request
            request_data: Request data dictionary
            handler: Async function to handle the request
            
        Returns:
            Request ID
        """
        request_id = f"{datetime.now().timestamp()}-{uuid.uuid4().hex[:8]}"
        request_data['request_id'] = request_id
        
        await self.queues[account_index].put({
            'request_id': request_id,
            'data': request_data,
            'handler': handler,
        })
        
        # Start worker if not already running
        if account_index not in self.workers or self.workers[account_index].done():
            self.workers[account_index] = asyncio.create_task(
                self._worker(account_index)
            )
        
        logger.info(f"Enqueued request {request_id} for account {account_index}")
        return request_id
    
    async def _worker(self, account_index: int):
        """Worker that processes requests from the queue."""
        logger.info(f"Started worker for account {account_index}")
        
        while self.running:
            try:
                # Wait for item with timeout to allow checking running status
                try:
                    item = await asyncio.wait_for(
                        self.queues[account_index].get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                request_id = item['request_id']
                request_data = item['data']
                handler = item['handler']
                
                logger.info(f"Processing request {request_id} for account {account_index}")
                
                try:
                    await handler(request_data)
                except Exception as e:
                    logger.error(
                        f"Error processing request {request_id}: {e}",
                        exc_info=True
                    )
                
                self.queues[account_index].task_done()
                
            except Exception as e:
                logger.error(f"Worker error for account {account_index}: {e}", exc_info=True)
        
        logger.info(f"Worker stopped for account {account_index}")
    
    async def shutdown(self):
        """Shutdown all workers gracefully."""
        logger.info("Shutting down queue manager")
        self.running = False
        
        # Wait for all queues to be processed
        for account_index, queue in self.queues.items():
            await queue.join()
        
        # Cancel all workers
        for account_index, worker in self.workers.items():
            if not worker.done():
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
        
        logger.info("Queue manager shut down complete")


# Global queue manager instance
_queue_manager: QueueManager = None


def get_queue_manager() -> QueueManager:
    """Get the global queue manager instance."""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = QueueManager()
    return _queue_manager

