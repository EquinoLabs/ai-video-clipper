"""Background processing worker entrypoint."""

import asyncio
import logging
import signal
from app.core.config import get_settings
from app.core.logging import setup_logging

logger = logging.getLogger("ai_video_clipper.worker")


class WorkerProcess:
    """Manages the background job claim, execution loop, and graceful shutdown."""

    def __init__(self):
        self.settings = get_settings()
        self.running = False

    async def start(self) -> None:
        """Start worker loop with heartbeat and atomic job claiming."""
        setup_logging(self.settings.log_level)
        logger.info(
            f"Starting worker process (concurrency={self.settings.worker_concurrency}, "
            f"env={self.settings.environment})"
        )
        self.running = True

        # In Phase 4, the queue claim loop will poll the database for queued jobs.
        # For setup/proof, the worker can be initialized and verified.
        while self.running:
            await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal worker to stop gracefully."""
        logger.info("Stopping worker process...")
        self.running = False


def run_worker() -> None:
    """CLI entrypoint to run the worker process."""
    worker = WorkerProcess()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal():
        worker.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, AttributeError):
            # Windows signal handlers may not support add_signal_handler for all signals
            pass

    try:
        loop.run_until_complete(worker.start())
    except KeyboardInterrupt:
        worker.stop()
    finally:
        loop.close()


if __name__ == "__main__":
    run_worker()
