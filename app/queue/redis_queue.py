import json
from typing import Optional, Any
import redis
from app.config import get_settings
from app.observability.logger import get_logger


class RedisQueue:
    """Redis-backed event queue using Lists."""

    QUEUE_KEY = "asana_trello:queue"
    DLQ_KEY = "asana_trello:dlq"
    DEDUP_KEY = "asana_trello:dedup:events"

    def __init__(self):
        settings = get_settings()
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        self.logger = get_logger(__name__)

    def enqueue(self, event: dict) -> bool:
        """
        Enqueue an event to the main queue.
        
        Args:
            event: Event payload dict
        
        Returns:
            True if enqueued successfully
        """
        try:
            event_json = json.dumps(event)
            self.redis_client.lpush(self.QUEUE_KEY, event_json)
            self.logger.info(
                "Event enqueued",
                event_id=event.get("id"),
                queue_key=self.QUEUE_KEY,
            )
            return True
        except Exception as e:
            self.logger.error(
                "Failed to enqueue event",
                error=str(e),
                event_id=event.get("id"),
            )
            return False

    def dequeue(self, timeout: int = 1) -> Optional[dict]:
        """
        Dequeue an event from the main queue (blocking).
        
        Args:
            timeout: Blocking timeout in seconds
        
        Returns:
            Event dict or None if queue is empty
        """
        try:
            result = self.redis_client.brpop(self.QUEUE_KEY, timeout=timeout)
            if result:
                _, event_json = result
                event = json.loads(event_json)
                self.logger.info(
                    "Event dequeued",
                    event_id=event.get("id"),
                )
                return event
            return None
        except Exception as e:
            self.logger.error("Failed to dequeue event", error=str(e))
            return None

    def push_to_dlq(
        self,
        event: dict,
        failure_reason: str,
        error_code: Optional[str] = None,
        attempt_count: int = 0,
    ) -> bool:
        """
        Push an event to the dead-letter queue.
        
        Args:
            event: Original event payload
            failure_reason: Reason for DLQ push
            error_code: Optional error code
            attempt_count: Number of attempts made
        
        Returns:
            True if pushed successfully
        """
        try:
            dlq_record = {
                "event": event,
                "failure_reason": failure_reason,
                "error_code": error_code,
                "attempt_count": attempt_count,
                "timestamp": self.redis_client.time()[0],
            }
            dlq_json = json.dumps(dlq_record)
            self.redis_client.lpush(self.DLQ_KEY, dlq_json)
            self.logger.warning(
                "Event pushed to DLQ",
                event_id=event.get("id"),
                failure_reason=failure_reason,
                error_code=error_code,
            )
            return True
        except Exception as e:
            self.logger.error(
                "Failed to push event to DLQ",
                error=str(e),
                event_id=event.get("id"),
            )
            return False

    def mark_event_deduped(self, event_id: str) -> bool:
        """
        Mark an event as seen (for deduplication).
        
        Args:
            event_id: Asana event ID
        
        Returns:
            True if marked successfully
        """
        try:
            self.redis_client.setex(self.DEDUP_KEY + f":{event_id}", 86400, "1")
            return True
        except Exception as e:
            self.logger.error(
                "Failed to mark event as deduped",
                error=str(e),
                event_id=event_id,
            )
            return False

    def is_event_deduped(self, event_id: str) -> bool:
        """
        Check if an event has been seen before.
        
        Args:
            event_id: Asana event ID
        
        Returns:
            True if event was seen before
        """
        try:
            return self.redis_client.exists(self.DEDUP_KEY + f":{event_id}") > 0
        except Exception as e:
            self.logger.error(
                "Failed to check event dedup status",
                error=str(e),
                event_id=event_id,
            )
            return False

    def get_dlq_size(self) -> int:
        """Get the number of events in the DLQ."""
        try:
            return self.redis_client.llen(self.DLQ_KEY)
        except Exception as e:
            self.logger.error("Failed to get DLQ size", error=str(e))
            return 0

    def get_queue_size(self) -> int:
        """Get the number of events in the main queue."""
        try:
            return self.redis_client.llen(self.QUEUE_KEY)
        except Exception as e:
            self.logger.error("Failed to get queue size", error=str(e))
            return 0
