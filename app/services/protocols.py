"""Service interfaces using Protocol for dependency inversion."""

from typing import Protocol, Dict, Any, Optional, Tuple, List
from app.domain.models import TaskData


class EventValidatorProtocol(Protocol):
    """Interface for event validation."""
    
    def validate_event(self, event: Dict[str, Any]) -> Optional[str]:
        """Validate event structure and return error message if invalid."""
        ...
    
    def extract_task_info(self, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """Extract task_gid and section_gid from event."""
        ...


class TaskServiceProtocol(Protocol):
    """Interface for task-related operations."""
    
    async def get_task_data(self, task_gid: str) -> Optional[TaskData]:
        """Fetch and transform task data."""
        ...
    
    async def get_section_name(self, section_gid: str) -> Optional[str]:
        """Get section name from Asana."""
        ...


class CardServiceProtocol(Protocol):
    """Interface for card-related operations."""
    
    async def create_card_from_task(self, task_data: TaskData, list_id: str) -> Optional[str]:
        """Create Trello card with attachments from task data."""
        ...


class DeduplicationServiceProtocol(Protocol):
    """Interface for deduplication operations."""
    
    def acquire_lock(self, task_gid: str) -> bool:
        """Acquire distributed lock for task."""
        ...
    
    def release_lock(self, task_gid: str) -> None:
        """Release distributed lock for task."""
        ...
    
    def is_already_processed(self, task_gid: str) -> bool:
        """Check if task was already processed."""
        ...
    
    def mark_as_processed(self, task_gid: str, card_id: str, event_id: str) -> None:
        """Mark task as processed with mapping."""
        ...


class AsanaClientProtocol(Protocol):
    """Interface for Asana API operations."""
    
    async def get_task(self, task_gid: str) -> Optional[Dict[str, Any]]:
        """Fetch task details from Asana."""
        ...
    
    async def get_section(self, section_gid: str) -> Optional[str]:
        """Fetch section name from Asana."""
        ...


class TrelloClientProtocol(Protocol):
    """Interface for Trello API operations."""
    
    async def create_card(self, name: str, description: str, list_id: str) -> Optional[str]:
        """Create a card in Trello."""
        ...