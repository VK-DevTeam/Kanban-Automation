from typing import Optional, Dict, Any
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from app.config import get_settings
from app.observability.logger import get_logger
from app.services.protocols import TrelloClientProtocol


class TrelloClient:
    """Trello REST API client with retry logic."""

    BASE_URL = "https://api.trello.com/1"

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.trello_api_key
        self.token = settings.trello_token
        self.api_timeout = settings.api_timeout_seconds
        self.attachment_timeout = settings.attachment_timeout_seconds
        self.logger = get_logger(__name__)

    def _get_auth_params(self) -> Dict[str, str]:
        """Get authentication query parameters."""
        return {"key": self.api_key, "token": self.token}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def create_card(
        self, name: str, description: str, list_id: str
    ) -> Optional[str]:
        """
        Create a card in Trello.
        
        Args:
            name: Card name (verbatim from Asana)
            description: Card description (verbatim from Asana)
            list_id: Target list ID
        
        Returns:
            Card ID or None on error
        """
        try:
            async with httpx.AsyncClient(timeout=self.api_timeout) as client:
                response = await client.post(
                    f"{self.BASE_URL}/cards",
                    params={
                        **self._get_auth_params(),
                        "idList": list_id,
                        "name": name,
                        "desc": description,
                    },
                )

                if response.status_code == 401:
                    self.logger.error("Trello authentication failed", status=401)
                    raise Exception("Authentication failed")
                elif response.status_code == 403:
                    self.logger.error("Trello access forbidden", status=403)
                    raise Exception("Access forbidden")
                elif response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "60")
                    self.logger.warning(
                        "Rate limited by Trello",
                        retry_after=retry_after,
                    )
                    raise httpx.HTTPError(f"Rate limited, retry after {retry_after}s")

                response.raise_for_status()
                data = response.json()
                card_id = data.get("id")
                self.logger.info("Card created", card_id=card_id, list_id=list_id)
                return card_id

        except httpx.TimeoutException:
            self.logger.error("Trello API timeout")
            raise
        except httpx.HTTPError as e:
            self.logger.error("Trello API error", error=str(e))
            raise
        except Exception as e:
            self.logger.error("Unexpected error creating card", error=str(e))
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def upload_attachment(
        self, card_id: str, filename: str, file_bytes: bytes, mime_type: str
    ) -> bool:
        """
        Upload an attachment to a Trello card.
        
        Args:
            card_id: Target card ID
            filename: Original filename
            file_bytes: File content
            mime_type: MIME type
        
        Returns:
            True if uploaded successfully
        """
        try:
            async with httpx.AsyncClient(timeout=self.attachment_timeout) as client:
                files = {
                    "file": (filename, file_bytes, mime_type),
                }
                response = await client.post(
                    f"{self.BASE_URL}/cards/{card_id}/attachments",
                    params=self._get_auth_params(),
                    files=files,
                )

                if response.status_code == 401:
                    self.logger.error("Trello authentication failed", status=401)
                    raise Exception("Authentication failed")
                elif response.status_code == 403:
                    self.logger.error("Trello access forbidden", status=403)
                    raise Exception("Access forbidden")
                elif response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "60")
                    self.logger.warning(
                        "Rate limited by Trello",
                        retry_after=retry_after,
                    )
                    raise httpx.HTTPError(f"Rate limited, retry after {retry_after}s")

                response.raise_for_status()
                self.logger.info(
                    "Attachment uploaded",
                    card_id=card_id,
                    filename=filename,
                )
                return True

        except httpx.TimeoutException:
            self.logger.error(
                "Trello attachment upload timeout",
                card_id=card_id,
                filename=filename,
            )
            raise
        except httpx.HTTPError as e:
            self.logger.error(
                "Trello attachment upload error",
                error=str(e),
                card_id=card_id,
                filename=filename,
            )
            raise
        except Exception as e:
            self.logger.error(
                "Unexpected error uploading attachment",
                error=str(e),
                card_id=card_id,
                filename=filename,
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )
    async def append_card_description(self, card_id: str, note: str) -> bool:
        """
        Append text to a card's description.
        
        Args:
            card_id: Target card ID
            note: Text to append
        
        Returns:
            True if updated successfully
        """
        try:
            async with httpx.AsyncClient(timeout=self.api_timeout) as client:
                # First get current description
                get_response = await client.get(
                    f"{self.BASE_URL}/cards/{card_id}",
                    params={**self._get_auth_params(), "fields": "desc"},
                )
                get_response.raise_for_status()
                current_desc = get_response.json().get("desc", "")

                # Append note
                new_desc = f"{current_desc}\n\n{note}" if current_desc else note

                # Update description
                put_response = await client.put(
                    f"{self.BASE_URL}/cards/{card_id}",
                    params={**self._get_auth_params(), "desc": new_desc},
                )
                put_response.raise_for_status()
                self.logger.info("Card description updated", card_id=card_id)
                return True

        except Exception as e:
            self.logger.error(
                "Error appending to card description",
                error=str(e),
                card_id=card_id,
            )
            raise
