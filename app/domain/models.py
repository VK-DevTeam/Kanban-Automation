"""Domain models for the application."""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class TaskData:
    """Domain model for task data."""
    gid: str
    name: str
    notes: str
    attachments: List[Dict[str, Any]]


@dataclass
class ProcessingResult:
    """Result of event processing."""
    success: bool
    card_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None