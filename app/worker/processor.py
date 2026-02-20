import time
from typing import Dict, Any
from app.config import Settings
from app.observability.logger import get_logger, alert_dlq
from app.queue.redis_queue import RedisQueue
from app.domain.models import ProcessingResult
from app.services.protocols import (
    EventValidatorProtocol,
    TaskServiceProtocol,
    CardServiceProtocol,
    DeduplicationServiceProtocol,
)


class EventProcessor:
    """Orchestrates event processing using injected services."""

    def __init__(
        self,
        validator: EventValidatorProtocol,
        task_service: TaskServiceProtocol,
        card_service: CardServiceProtocol,
        dedup_service: DeduplicationServiceProtocol,
        settings: Settings,
    ) -> None:
        self.validator = validator
        self.task_service = task_service
        self.card_service = card_service
        self.dedup_service = dedup_service
        self.settings = settings
        self.logger = get_logger(__name__)
        self.queue = RedisQueue()

    async def process_event(self, event: Dict[str, Any]) -> ProcessingResult:
        """Process event using injected services."""
        event_id = event.get("id")
        start_time = time.time()

        try:
            # Step 1: Validate event
            validation_error = self.validator.validate_event(event)
            if validation_error:
                self.logger.info("Event filtered", reason=validation_error, event_id=event_id)
                return ProcessingResult(success=True)  # Not an error, just filtered

            # Step 2: Extract task information
            task_info = self.validator.extract_task_info(event)
            if not task_info:
                return ProcessingResult(
                    success=False,
                    error_code="INVALID_EVENT_STRUCTURE",
                    error_message="Missing task_gid or section_gid"
                )

            task_gid, section_gid = task_info

            # Step 3: Validate section
            section_name = await self.task_service.get_section_name(section_gid)
            if section_name != self.settings.asana_trigger_section_name:
                self.logger.info("Event filtered", reason="Section mismatch", event_id=event_id)
                return ProcessingResult(success=True)

            # Step 4: Handle deduplication with lock
            if not self.dedup_service.acquire_lock(task_gid):
                self.logger.info("Lock not acquired", task_gid=task_gid, event_id=event_id)
                return ProcessingResult(success=True)

            try:
                if self.dedup_service.is_already_processed(task_gid):
                    self.logger.info("Already processed", task_gid=task_gid, event_id=event_id)
                    return ProcessingResult(success=True)

                # Step 5: Get task data
                task_data = await self.task_service.get_task_data(task_gid)
                if not task_data:
                    await self._handle_error(
                        event, event_id, task_gid,
                        "Task not found in Asana", "ASANA_404"
                    )
                    return ProcessingResult(
                        success=False,
                        error_code="TASK_NOT_FOUND",
                        error_message="Task not found in Asana"
                    )

                # Step 6: Create card
                card_id = await self.card_service.create_card_from_task(
                    task_data, self.settings.trello_target_list_id
                )
                if not card_id:
                    await self._handle_error(
                        event, event_id, task_gid,
                        "Failed to create Trello card", "TRELLO_CREATE_FAILED"
                    )
                    return ProcessingResult(
                        success=False,
                        error_code="CARD_CREATION_FAILED",
                        error_message="Failed to create Trello card"
                    )

                # Step 7: Mark as processed
                self.dedup_service.mark_as_processed(task_gid, card_id, event_id)

                duration_ms = int((time.time() - start_time) * 1000)
                self.logger.info(
                    "Event processed successfully",
                    event_id=event_id,
                    task_gid=task_gid,
                    card_id=card_id,
                    duration_ms=duration_ms,
                )

                return ProcessingResult(success=True, card_id=card_id)

            finally:
                self.dedup_service.release_lock(task_gid)

        except Exception as e:
            self.logger.error(
                "Unhandled exception processing event",
                error=str(e),
                event_id=event_id,
                exc_info=True,
            )
            await self._handle_error(
                event, event_id, None,
                "Unhandled exception during event processing", "UNHANDLED_EXCEPTION",
                {"error": str(e)}
            )
            return ProcessingResult(
                success=False,
                error_code="UNHANDLED_EXCEPTION",
                error_message=str(e)
            )

    async def _handle_error(
        self, 
        event: Dict[str, Any], 
        event_id: str, 
        task_gid: str = None,
        reason: str = "", 
        error_code: str = "", 
        details: Dict[str, Any] = None
    ) -> None:
        """Handle error by alerting and pushing to DLQ."""
        await alert_dlq(
            reason=reason,
            error_code=error_code,
            event_id=event_id,
            task_gid=task_gid,
            details=details,
        )
        await self.queue.push_to_dlq(event, reason, error_code)
