"""Event validation service following Single Responsibility Principle."""

from typing import Dict, Any, Optional, Tuple
from app.observability.logger import get_logger


class EventValidator:
    """Validates and extracts information from Asana events."""
    
    def __init__(self, trigger_section_name: str) -> None:
        self.trigger_section_name = trigger_section_name
        self.logger = get_logger(__name__)

    def validate_event(self, event: Dict[str, Any]) -> Optional[str]:
        """Validate event structure and return error message if invalid."""
        if not self._is_section_changed_event(event):
            return "Not a section_changed event"
        return None

    def extract_task_info(self, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """Extract task_gid and section_gid from event."""
        resource = event.get("resource", {})
        task_gid = resource.get("gid")
        section_gid = event.get("data", {}).get("new_section", {}).get("gid")
        
        if not task_gid or not section_gid:
            return None
        return task_gid, section_gid

    def _is_section_changed_event(self, event: Dict[str, Any]) -> bool:
        """Check if event is a task.section_changed event."""
        events = event.get("events", [])
        if not events:
            return False

        for evt in events:
            if evt.get("type") == "task" and evt.get("action") == "changed":
                # Check if section was changed
                if "new_section" in evt.get("data", {}):
                    return True

        return False