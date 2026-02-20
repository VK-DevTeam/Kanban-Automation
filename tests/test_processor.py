import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.worker.processor import EventProcessor
from app.queue.redis_queue import RedisQueue
from app.worker.deduplication import Deduplication


@pytest.fixture
def processor():
    return EventProcessor()


@pytest.fixture
def section_changed_event():
    """Create a valid section_changed event."""
    return {
        "id": "event-123",
        "created_at": "2026-02-19T10:00:00Z",
        "resource": {"gid": "task-456"},
        "events": [
            {
                "type": "task",
                "action": "changed",
                "data": {
                    "new_section": {"gid": "section-789"}
                },
            }
        ],
    }


@pytest.mark.asyncio
async def test_event_filtered_wrong_event_type(processor):
    """Test that non-section_changed events are filtered."""
    event = {
        "id": "event-123",
        "events": [
            {
                "type": "task",
                "action": "created",
            }
        ],
    }

    result = await processor.process_event(event)
    assert result is True  # Filtered events return True (no error)


@pytest.mark.asyncio
async def test_event_filtered_wrong_section(processor, section_changed_event):
    """Test that events for non-trigger sections are filtered."""
    with patch.object(
        processor.asana_client, "get_section", new_callable=AsyncMock
    ) as mock_get_section:
        mock_get_section.return_value = "Some Other Section"

        result = await processor.process_event(section_changed_event)
        assert result is True  # Filtered events return True


@pytest.mark.asyncio
async def test_task_not_found_pushed_to_dlq(processor, section_changed_event):
    """Test that 404 task errors are pushed to DLQ."""
    with patch.object(
        processor.asana_client, "get_section", new_callable=AsyncMock
    ) as mock_get_section, patch.object(
        processor.asana_client, "get_task", new_callable=AsyncMock
    ) as mock_get_task, patch.object(
        processor.dedup, "acquire_lock", return_value=True
    ), patch.object(
        processor.dedup, "get_mapping", return_value=None
    ), patch.object(
        processor.queue, "push_to_dlq", new_callable=AsyncMock
    ) as mock_push_dlq:

        mock_get_section.return_value = processor.settings.asana_trigger_section_name
        mock_get_task.return_value = None

        result = await processor.process_event(section_changed_event)
        assert result is False
        mock_push_dlq.assert_called_once()


@pytest.mark.asyncio
async def test_dedup_prevents_duplicate_card(processor, section_changed_event):
    """Test that dedup mapping prevents duplicate card creation."""
    existing_mapping = {
        "asana_task_gid": "task-456",
        "trello_card_id": "card-999",
        "created_at": 1234567890,
        "trigger_event_id": "event-old",
        "trigger_timestamp": 1234567890,
    }

    with patch.object(
        processor.asana_client, "get_section", new_callable=AsyncMock
    ) as mock_get_section, patch.object(
        processor.dedup, "acquire_lock", return_value=True
    ), patch.object(
        processor.dedup, "get_mapping", return_value=existing_mapping
    ), patch.object(
        processor.trello_client, "create_card", new_callable=AsyncMock
    ) as mock_create_card:

        mock_get_section.return_value = processor.settings.asana_trigger_section_name

        result = await processor.process_event(section_changed_event)
        assert result is True
        mock_create_card.assert_not_called()


@pytest.mark.asyncio
async def test_lock_not_acquired_concurrent_worker(processor, section_changed_event):
    """Test that concurrent workers don't create duplicate cards."""
    with patch.object(
        processor.dedup, "acquire_lock", return_value=False
    ):
        result = await processor.process_event(section_changed_event)
        assert result is True  # Returns True, doesn't error


@pytest.mark.asyncio
async def test_card_created_with_exact_name_and_description(
    processor, section_changed_event
):
    """Test that Trello card name and description match Asana exactly."""
    task_data = {
        "name": "Task with émojis 🎉 and spëcial çhars",
        "notes": "Description with\nmultiple\nlines",
        "attachments": [],
    }

    with patch.object(
        processor.asana_client, "get_section", new_callable=AsyncMock
    ) as mock_get_section, patch.object(
        processor.asana_client, "get_task", new_callable=AsyncMock
    ) as mock_get_task, patch.object(
        processor.dedup, "acquire_lock", return_value=True
    ), patch.object(
        processor.dedup, "get_mapping", return_value=None
    ), patch.object(
        processor.trello_client, "create_card", new_callable=AsyncMock
    ) as mock_create_card, patch.object(
        processor.dedup, "set_mapping", return_value=True
    ):

        mock_get_section.return_value = processor.settings.asana_trigger_section_name
        mock_get_task.return_value = task_data
        mock_create_card.return_value = "card-123"

        result = await processor.process_event(section_changed_event)
        assert result is True

        # Verify exact name and description passed
        mock_create_card.assert_called_once()
        call_args = mock_create_card.call_args
        assert call_args.kwargs["name"] == task_data["name"]
        assert call_args.kwargs["description"] == task_data["notes"]


@pytest.mark.asyncio
async def test_empty_description_passed_as_empty_string(processor, section_changed_event):
    """Test that tasks with no description get empty string, not default text."""
    task_data = {
        "name": "Task Name",
        "notes": "",
        "attachments": [],
    }

    with patch.object(
        processor.asana_client, "get_section", new_callable=AsyncMock
    ) as mock_get_section, patch.object(
        processor.asana_client, "get_task", new_callable=AsyncMock
    ) as mock_get_task, patch.object(
        processor.dedup, "acquire_lock", return_value=True
    ), patch.object(
        processor.dedup, "get_mapping", return_value=None
    ), patch.object(
        processor.trello_client, "create_card", new_callable=AsyncMock
    ) as mock_create_card, patch.object(
        processor.dedup, "set_mapping", return_value=True
    ):

        mock_get_section.return_value = processor.settings.asana_trigger_section_name
        mock_get_task.return_value = task_data
        mock_create_card.return_value = "card-123"

        result = await processor.process_event(section_changed_event)
        assert result is True

        call_args = mock_create_card.call_args
        assert call_args.kwargs["description"] == ""


@pytest.mark.asyncio
async def test_section_name_case_sensitive(processor, section_changed_event):
    """Test that section name matching is case-sensitive."""
    with patch.object(
        processor.asana_client, "get_section", new_callable=AsyncMock
    ) as mock_get_section:
        # Return lowercase version
        mock_get_section.return_value = "vk-allocate rjob"

        result = await processor.process_event(section_changed_event)
        assert result is True  # Filtered


@pytest.mark.asyncio
async def test_section_name_whitespace_sensitive(processor, section_changed_event):
    """Test that section name matching is whitespace-sensitive."""
    with patch.object(
        processor.asana_client, "get_section", new_callable=AsyncMock
    ) as mock_get_section:
        # Return with trailing space
        mock_get_section.return_value = "VK-Allocate Rjob "

        result = await processor.process_event(section_changed_event)
        assert result is True  # Filtered
