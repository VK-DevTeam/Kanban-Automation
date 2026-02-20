from typing import List, Dict, Any, Optional
from io import BytesIO
import httpx
from app.config import get_settings
from app.observability.logger import get_logger
from app.worker.trello_client import TrelloClient


class AttachmentProcessor:
    """Handle downloading Asana attachments and uploading to Trello."""

    # Trello free plan limit: 10MB per attachment
    TRELLO_FREE_LIMIT = 10 * 1024 * 1024  # 10MB
    TRELLO_PREMIUM_LIMIT = 250 * 1024 * 1024  # 250MB

    def __init__(self, is_premium: bool = False):
        settings = get_settings()
        self.attachment_timeout = settings.attachment_timeout_seconds
        self.trello_client = TrelloClient()
        self.logger = get_logger(__name__)
        self.size_limit = (
            self.TRELLO_PREMIUM_LIMIT if is_premium else self.TRELLO_FREE_LIMIT
        )

    async def process_attachments(
        self,
        attachments: List[Dict[str, Any]],
        card_id: str,
        task_gid: str,
    ) -> Dict[str, Any]:
        """
        Process all attachments for a task.
        
        Args:
            attachments: List of attachment dicts from Asana
            card_id: Target Trello card ID
            task_gid: Source Asana task GID
        
        Returns:
            Dict with success_count, failed_count, skipped_count, oversized_files
        """
        result = {
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "oversized_files": [],
        }

        if not attachments:
            self.logger.info("No attachments to process", task_gid=task_gid)
            return result

        for attachment in attachments:
            attachment_result = await self._process_single_attachment(
                attachment, card_id, task_gid
            )

            if attachment_result["status"] == "success":
                result["success_count"] += 1
            elif attachment_result["status"] == "oversized":
                result["skipped_count"] += 1
                result["oversized_files"].append(attachment_result["filename"])
            elif attachment_result["status"] == "failed":
                result["failed_count"] += 1

        # Append notice if there were oversized files
        if result["oversized_files"]:
            notice = f"⚠️ The following attachments exceeded Trello's size limit and were not uploaded:\n"
            for filename in result["oversized_files"]:
                notice += f"- {filename}\n"
            try:
                await self.trello_client.append_card_description(card_id, notice)
            except Exception as e:
                self.logger.error(
                    "Failed to append oversized attachment notice",
                    error=str(e),
                    card_id=card_id,
                )

        self.logger.info(
            "Attachment processing complete",
            task_gid=task_gid,
            card_id=card_id,
            success=result["success_count"],
            failed=result["failed_count"],
            skipped=result["skipped_count"],
        )

        return result

    async def _process_single_attachment(
        self,
        attachment: Dict[str, Any],
        card_id: str,
        task_gid: str,
    ) -> Dict[str, Any]:
        """
        Process a single attachment.
        
        Args:
            attachment: Attachment dict from Asana
            card_id: Target Trello card ID
            task_gid: Source Asana task GID
        
        Returns:
            Dict with status (success/failed/oversized) and filename
        """
        filename = attachment.get("name", "attachment")
        size = attachment.get("size", 0)
        download_url = attachment.get("download_url")
        mime_type = attachment.get("mime_type", "application/octet-stream")

        # Check size limit
        if size > self.size_limit:
            self.logger.warning(
                "Attachment exceeds size limit",
                filename=filename,
                size=size,
                limit=self.size_limit,
                task_gid=task_gid,
            )
            return {"status": "oversized", "filename": filename}

        if not download_url:
            self.logger.warning(
                "Attachment missing download URL",
                filename=filename,
                task_gid=task_gid,
            )
            return {"status": "failed", "filename": filename}

        try:
            # Download from Asana
            file_bytes = await self._download_attachment(download_url)

            # Upload to Trello
            await self.trello_client.upload_attachment(
                card_id, filename, file_bytes, mime_type
            )

            self.logger.info(
                "Attachment processed successfully",
                filename=filename,
                task_gid=task_gid,
                card_id=card_id,
            )
            return {"status": "success", "filename": filename}

        except Exception as e:
            self.logger.error(
                "Failed to process attachment",
                error=str(e),
                filename=filename,
                task_gid=task_gid,
            )
            return {"status": "failed", "filename": filename}

    async def _download_attachment(self, download_url: str) -> bytes:
        """
        Download attachment from Asana using streaming.
        
        Args:
            download_url: Asana attachment download URL
        
        Returns:
            File bytes
        """
        try:
            async with httpx.AsyncClient(timeout=self.attachment_timeout) as client:
                response = await client.get(download_url, follow_redirects=True)
                response.raise_for_status()
                return response.content
        except Exception as e:
            self.logger.error("Failed to download attachment", error=str(e))
            raise
