import json
import time
from typing import Optional, Dict, Any
import redis
from app.config import get_settings
from app.observability.logger import get_logger


class Deduplication:
    """Distributed lock and mapping store for idempotency."""

    LOCK_PREFIX = "asana_trello:lock:task:"
    MAPPING_KEY = "asana_trello:task_card_map"
    LOCK_TIMEOUT = 60  # seconds

    def __init__(self):
        settings = get_settings()
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        self.logger = get_logger(__name__)

    def acquire_lock(self, task_gid: str) -> bool:
        """
        Acquire a distributed lock for a task.
        
        Args:
            task_gid: Task GID
        
        Returns:
            True if lock acquired, False if already locked
        """
        try:
            lock_key = f"{self.LOCK_PREFIX}{task_gid}"
            acquired = self.redis_client.set(
                lock_key, "1", nx=True, ex=self.LOCK_TIMEOUT
            )
            if acquired:
                self.logger.info("Lock acquired", task_gid=task_gid, lock_key=lock_key)
            else:
                self.logger.info("Lock already held", task_gid=task_gid, lock_key=lock_key)
            return bool(acquired)
        except Exception as e:
            self.logger.error("Failed to acquire lock", error=str(e), task_gid=task_gid)
            return False

    def release_lock(self, task_gid: str) -> bool:
        """
        Release a distributed lock for a task.
        
        Args:
            task_gid: Task GID
        
        Returns:
            True if lock released
        """
        try:
            lock_key = f"{self.LOCK_PREFIX}{task_gid}"
            self.redis_client.delete(lock_key)
            self.logger.info("Lock released", task_gid=task_gid, lock_key=lock_key)
            return True
        except Exception as e:
            self.logger.error("Failed to release lock", error=str(e), task_gid=task_gid)
            return False

    def get_mapping(self, task_gid: str) -> Optional[Dict[str, Any]]:
        """
        Get the task-to-card mapping if it exists.
        
        Args:
            task_gid: Task GID
        
        Returns:
            Mapping dict or None if not found
        """
        try:
            mapping_json = self.redis_client.hget(self.MAPPING_KEY, task_gid)
            if mapping_json:
                mapping = json.loads(mapping_json)
                self.logger.info(
                    "Mapping found",
                    task_gid=task_gid,
                    trello_card_id=mapping.get("trello_card_id"),
                )
                return mapping
            return None
        except Exception as e:
            self.logger.error(
                "Failed to get mapping",
                error=str(e),
                task_gid=task_gid,
            )
            return None

    def set_mapping(
        self,
        task_gid: str,
        trello_card_id: str,
        trigger_event_id: str,
        trigger_timestamp: int,
    ) -> bool:
        """
        Store a task-to-card mapping.
        
        Args:
            task_gid: Asana task GID
            trello_card_id: Trello card ID
            trigger_event_id: Asana event ID that triggered creation
            trigger_timestamp: Unix timestamp of trigger
        
        Returns:
            True if mapping stored successfully
        """
        try:
            mapping = {
                "asana_task_gid": task_gid,
                "trello_card_id": trello_card_id,
                "created_at": int(time.time()),
                "trigger_event_id": trigger_event_id,
                "trigger_timestamp": trigger_timestamp,
            }
            mapping_json = json.dumps(mapping)
            self.redis_client.hset(self.MAPPING_KEY, task_gid, mapping_json)
            self.logger.info(
                "Mapping stored",
                task_gid=task_gid,
                trello_card_id=trello_card_id,
            )
            return True
        except Exception as e:
            self.logger.error(
                "Failed to set mapping",
                error=str(e),
                task_gid=task_gid,
            )
            return False
