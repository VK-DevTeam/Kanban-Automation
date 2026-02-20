"""Test the SOLID principles refactoring."""

import pytest
from unittest.mock import AsyncMock, Mock
from app.container import create_container
from app.services.protocols import (
    EventValidatorProtocol,
    TaskServiceProtocol,
    CardServiceProtocol,
    DeduplicationServiceProtocol,
)
from app.worker.processor import EventProcessor
from app.config import get_settings
from app.domain.models import TaskData, ProcessingResult


class TestSOLIDRefactoring:
    """Test that the SOLID refactoring works correctly."""

    def test_container_creates_services(self):
        """Test that the DI container creates all required services."""
        container = create_container()
        
        # Verify all services can be created
        validator = container.get(EventValidatorProtocol)
        task_service = container.get(TaskServiceProtocol)
        card_service = container.get(CardServiceProtocol)
        dedup_service = container.get(DeduplicationServiceProtocol)
        
        assert validator is not None
        assert task_service is not None
        assert card_service is not None
        assert dedup_service is not None

    def test_event_processor_with_dependency_injection(self):
        """Test that EventProcessor works with injected dependencies."""
        # Create mock services
        validator = Mock(spec=EventValidatorProtocol)
        task_service = Mock(spec=TaskServiceProtocol)
        card_service = Mock(spec=CardServiceProtocol)
        dedup_service = Mock(spec=DeduplicationServiceProtocol)
        
        # Create processor with injected dependencies
        processor = EventProcessor(
            validator=validator,
            task_service=task_service,
            card_service=card_service,
            dedup_service=dedup_service,
            settings=get_settings(),
        )
        
        assert processor.validator is validator
        assert processor.task_service is task_service
        assert processor.card_service is card_service
        assert processor.dedup_service is dedup_service

    @pytest.mark.asyncio
    async def test_event_processing_flow(self):
        """Test the complete event processing flow with mocked services."""
        # Setup mocks
        validator = Mock(spec=EventValidatorProtocol)
        task_service = AsyncMock(spec=TaskServiceProtocol)
        card_service = AsyncMock(spec=CardServiceProtocol)
        dedup_service = Mock(spec=DeduplicationServiceProtocol)
        
        # Configure mock behavior
        validator.validate_event.return_value = None  # Valid event
        validator.extract_task_info.return_value = ("task_123", "section_456")
        task_service.get_section_name.return_value = "Ready for Development"
        dedup_service.acquire_lock.return_value = True
        dedup_service.is_already_processed.return_value = False
        
        task_data = TaskData(
            gid="task_123",
            name="Test Task",
            notes="Test notes",
            attachments=[]
        )
        task_service.get_task_data.return_value = task_data
        card_service.create_card_from_task.return_value = "card_789"
        
        # Create processor
        settings = get_settings()
        settings.asana_trigger_section_name = "Ready for Development"
        
        processor = EventProcessor(
            validator=validator,
            task_service=task_service,
            card_service=card_service,
            dedup_service=dedup_service,
            settings=settings,
        )
        
        # Test event processing
        event = {
            "id": "event_123",
            "resource": {"gid": "task_123"},
            "data": {"new_section": {"gid": "section_456"}},
            "events": [{"type": "task", "action": "changed", "data": {"new_section": {}}}]
        }
        
        result = await processor.process_event(event)
        
        # Verify result
        assert isinstance(result, ProcessingResult)
        assert result.success is True
        assert result.card_id == "card_789"
        
        # Verify service calls
        validator.validate_event.assert_called_once_with(event)
        validator.extract_task_info.assert_called_once_with(event)
        task_service.get_section_name.assert_called_once_with("section_456")
        dedup_service.acquire_lock.assert_called_once_with("task_123")
        dedup_service.is_already_processed.assert_called_once_with("task_123")
        task_service.get_task_data.assert_called_once_with("task_123")
        card_service.create_card_from_task.assert_called_once()
        dedup_service.mark_as_processed.assert_called_once_with("task_123", "card_789", "event_123")
        dedup_service.release_lock.assert_called_once_with("task_123")