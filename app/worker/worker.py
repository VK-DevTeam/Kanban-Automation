import asyncio
import time
from app.observability.logger import setup_logging, get_logger, alert_dlq
from app.queue.redis_queue import RedisQueue
from app.worker.processor import EventProcessor
from app.container import create_container
from app.config import get_settings
from app.services.protocols import (
    EventValidatorProtocol,
    TaskServiceProtocol,
    CardServiceProtocol,
    DeduplicationServiceProtocol,
)


async def worker_loop():
    """
    Main consumer loop with dependency injection.
    
    Continuously dequeues events and processes them.
    On unhandled exception, logs and pushes to DLQ.
    """
    setup_logging()
    logger = get_logger(__name__)
    
    # Create DI container
    container = create_container()
    
    # Get services from container
    queue = RedisQueue()
    processor = EventProcessor(
        validator=container.get(EventValidatorProtocol),
        task_service=container.get(TaskServiceProtocol),
        card_service=container.get(CardServiceProtocol),
        dedup_service=container.get(DeduplicationServiceProtocol),
        settings=get_settings(),
    )

    logger.info("Worker started with dependency injection")

    last_processed_time = time.time()
    inactivity_threshold = 30 * 60  # 30 minutes

    while True:
        try:
            # Dequeue event (blocking with 1s timeout)
            event = queue.dequeue(timeout=1)

            if event:
                last_processed_time = time.time()

                # Check for duplicate webhook delivery
                event_id = event.get("id")
                if queue.is_event_deduped(event_id):
                    logger.info(
                        "Duplicate webhook delivery detected",
                        event_id=event_id,
                    )
                    continue

                # Mark as seen
                queue.mark_event_deduped(event_id)

                # Process event
                result = await processor.process_event(event)

                if not result.success:
                    logger.warning(
                        "Event processing failed",
                        event_id=event_id,
                        error_code=result.error_code,
                        error_message=result.error_message,
                    )
            else:
                # Check for inactivity
                current_time = time.time()
                if current_time - last_processed_time > inactivity_threshold:
                    logger.warning(
                        "No events processed in 30 minutes",
                        last_processed_time=last_processed_time,
                    )
                    await alert_dlq(
                        reason="No events processed in 30 minutes - worker may be stalled"
                    )
                    last_processed_time = current_time

        except Exception as e:
            logger.error(
                "Unhandled exception in worker loop",
                error=str(e),
                exc_info=True,
            )
            await alert_dlq(
                reason="Unhandled exception in worker loop",
                error_code="WORKER_EXCEPTION",
                details={"error": str(e)},
            )
            # Continue processing
            await asyncio.sleep(5)


def main():
    """Entry point for worker process."""
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
