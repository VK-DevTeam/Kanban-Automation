from typing import Optional, Dict, Any, List
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError,
)
from app.config import get_settings
from app.observability.logger import get_logger
from app.services.protocols import AsanaClientProtocol


class AsanaClient:
    """Asana REST API client with retry logic."""

    BASE_URL = "https://app.asana.com/api/1.0"

    def __init__(self):
        settings = get_settings()
        self.access_token = settings.asana_access_token
        self.timeout = settings.api_timeout_seconds
        self.max_retries = settings.max_retry_attempts
        self.logger = get_logger(__name__)

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def get_task(self, task_gid: str) -> Optional[Dict[str, Any]]:
        """
        Fetch task details from Asana.
        
        Args:
            task_gid: Task GID
        
        Returns:
            Task dict with name, notes, attachments, or None on error
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.BASE_URL}/tasks/{task_gid}",
                    headers=self._get_headers(),
                    params={"opt_fields": "name,notes,attachments.name,attachments.download_url,attachments.size,attachments.mime_type"},
                )

                if response.status_code == 401:
                    self.logger.error("Asana authentication failed", status=401)
                    raise Exception("Authentication failed")
                elif response.status_code == 403:
                    self.logger.error("Asana access forbidden", status=403)
                    raise Exception("Access forbidden")
                elif response.status_code == 404:
                    self.logger.warning("Task not found", task_gid=task_gid, status=404)
                    return None
                elif response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "60")
                    self.logger.warning(
                        "Rate limited by Asana",
                        retry_after=retry_after,
                    )
                    raise httpx.HTTPError(f"Rate limited, retry after {retry_after}s")

                response.raise_for_status()
                data = response.json()
                return data.get("data")

        except httpx.TimeoutException:
            self.logger.error("Asana API timeout", task_gid=task_gid)
            raise
        except httpx.HTTPError as e:
            self.logger.error("Asana API error", error=str(e), task_gid=task_gid)
            raise
        except Exception as e:
            self.logger.error("Unexpected error fetching task", error=str(e), task_gid=task_gid)
            raise

    async def get_section(self, section_gid: str) -> Optional[str]:
        """
        Fetch section name from Asana.
        
        Args:
            section_gid: Section GID
        
        Returns:
            Section name or None on error
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.BASE_URL}/sections/{section_gid}",
                    headers=self._get_headers(),
                    params={"opt_fields": "name"},
                )

                if response.status_code in (401, 403, 404):
                    self.logger.warning(
                        "Failed to fetch section",
                        section_gid=section_gid,
                        status=response.status_code,
                    )
                    return None

                response.raise_for_status()
                data = response.json()
                return data.get("data", {}).get("name")

        except Exception as e:
            self.logger.error(
                "Error fetching section",
                error=str(e),
                section_gid=section_gid,
            )
            return None

    async def get_attachment(
        self, attachment_gid: str
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch attachment metadata from Asana.
        
        Args:
            attachment_gid: Attachment GID
        
        Returns:
            Attachment dict with name, download_url, size, mime_type, or None on error
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.BASE_URL}/attachments/{attachment_gid}",
                    headers=self._get_headers(),
                    params={"opt_fields": "name,download_url,size,mime_type"},
                )

                if response.status_code in (401, 403, 404):
                    self.logger.warning(
                        "Failed to fetch attachment",
                        attachment_gid=attachment_gid,
                        status=response.status_code,
                    )
                    return None

                response.raise_for_status()
                data = response.json()
                return data.get("data")

        except Exception as e:
            self.logger.error(
                "Error fetching attachment",
                error=str(e),
                attachment_gid=attachment_gid,
            )
            return None
