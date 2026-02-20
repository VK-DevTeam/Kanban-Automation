"""Deduplication service adapter."""

import time
from app.worker.deduplication import Deduplication
from app.observability.logger import get_logger


class DeduplicationService:
    """Service adapter for deduplication operations."""
    
    def __init__(self, dedup: Deduplication) -> None:
        self.dedup = dedup
        self.logger = get_logger(__name__)

    def acquire_lock(self, task_gid: str) -> bool:
        """Acquire distributed lock for task."""
        return self.dedup.acquire_lock(task_gid)
    
    def release_lock(self, task_gid: str) -> None:
        """Release distributed lock for task."""
        self.dedup.release_lock(task_gid)
    
    def is_already_processed(self, task_gid: str) -> bool:
        """Check if task was already processed."""
        existing_mapping = self.dedup.get_mapping(task_gid)
        return existing_mapping is not None
    
    def mark_as_processed(self, task_gid: str, card_id: str, event_id: str) -> None:
        """Mark task as processed with mapping."""
        event_timestamp = int(time.time())
        self.dedup.set_mapping(
            task_gid=task_gid,
            trello_card_id=card_id,
            trigger_event_id=event_id,
            trigger_timestamp=event_timestamp,
        )