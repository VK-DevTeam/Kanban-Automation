import pytest
import json
import time
from app.worker.deduplication import Deduplication


@pytest.fixture
def dedup():
    return Deduplication()


def test_acquire_lock_success(dedup):
    """Test acquiring a lock."""
    task_gid = "test-task-123"
    result = dedup.acquire_lock(task_gid)
    assert result is True

    # Cleanup
    dedup.release_lock(task_gid)


def test_acquire_lock_already_held(dedup):
    """Test that lock cannot be acquired twice."""
    task_gid = "test-task-456"

    # First acquisition
    result1 = dedup.acquire_lock(task_gid)
    assert result1 is True

    # Second acquisition should fail
    result2 = dedup.acquire_lock(task_gid)
    assert result2 is False

    # Cleanup
    dedup.release_lock(task_gid)


def test_release_lock(dedup):
    """Test releasing a lock."""
    task_gid = "test-task-789"

    dedup.acquire_lock(task_gid)
    result = dedup.release_lock(task_gid)
    assert result is True

    # Should be able to acquire again
    result2 = dedup.acquire_lock(task_gid)
    assert result2 is True

    # Cleanup
    dedup.release_lock(task_gid)


def test_set_and_get_mapping(dedup):
    """Test storing and retrieving task-to-card mapping."""
    task_gid = "task-111"
    card_id = "card-222"
    event_id = "event-333"
    timestamp = int(time.time())

    # Set mapping
    result = dedup.set_mapping(task_gid, card_id, event_id, timestamp)
    assert result is True

    # Get mapping
    mapping = dedup.get_mapping(task_gid)
    assert mapping is not None
    assert mapping["asana_task_gid"] == task_gid
    assert mapping["trello_card_id"] == card_id
    assert mapping["trigger_event_id"] == event_id
    assert mapping["trigger_timestamp"] == timestamp


def test_get_mapping_not_found(dedup):
    """Test getting a mapping that doesn't exist."""
    task_gid = "nonexistent-task"
    mapping = dedup.get_mapping(task_gid)
    assert mapping is None


def test_mapping_persists_across_instances(dedup):
    """Test that mappings persist in Redis across instances."""
    task_gid = "task-persistent"
    card_id = "card-persistent"
    event_id = "event-persistent"
    timestamp = int(time.time())

    # Set mapping with first instance
    dedup.set_mapping(task_gid, card_id, event_id, timestamp)

    # Create new instance and retrieve
    dedup2 = Deduplication()
    mapping = dedup2.get_mapping(task_gid)
    assert mapping is not None
    assert mapping["trello_card_id"] == card_id
