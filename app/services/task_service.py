"""Task service for fetching task data from Asana."""

from typing import Optional
from app.domain.models import TaskData
from app.services.protocols import AsanaClientProtocol
from app.observability.logger import get_logger


class TaskService:
    """Service for fetching task data from Asana."""
    
    def __init__(self, asana_client: AsanaClientProtocol) -> None:
        self.asana_client = asana_client
        self.logger = get_logger(__name__)

    async def get_task_data(self, task_gid: str) -> Optional[TaskData]:
        """Fetch and transform task data."""
        raw_task = await self.asana_client.get_task(task_gid)
        if not raw_task:
            return None
        
        return TaskData(
            gid=task_gid,
            name=raw_task.get("name", ""),
            notes=raw_task.get("notes", ""),
            attachments=raw_task.get("attachments", [])
        )

    async def get_section_name(self, section_gid: str) -> Optional[str]:
        """Get section name from Asana."""
        return await self.asana_client.get_section(section_gid)