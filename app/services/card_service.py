"""Card service for creating cards in Trello."""

from typing import Optional
from app.domain.models import TaskData
from app.services.protocols import TrelloClientProtocol
from app.worker.attachments import AttachmentProcessor
from app.observability.logger import get_logger


class CardService:
    """Service for creating cards in Trello."""
    
    def __init__(self, trello_client: TrelloClientProtocol, attachment_processor: AttachmentProcessor) -> None:
        self.trello_client = trello_client
        self.attachment_processor = attachment_processor
        self.logger = get_logger(__name__)

    async def create_card_from_task(self, task_data: TaskData, list_id: str) -> Optional[str]:
        """Create Trello card with attachments from task data."""
        card_id = await self.trello_client.create_card(
            name=task_data.name,
            description=task_data.notes,
            list_id=list_id
        )
        
        if not card_id:
            return None

        # Process attachments
        if task_data.attachments:
            await self.attachment_processor.process_attachments(
                task_data.attachments, card_id, task_data.gid
            )
        
        return card_id