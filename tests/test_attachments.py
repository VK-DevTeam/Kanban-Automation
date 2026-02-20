import pytest
from unittest.mock import AsyncMock, patch
from app.worker.attachments import AttachmentProcessor


@pytest.fixture
def processor():
    return AttachmentProcessor(is_premium=False)


@pytest.fixture
def processor_premium():
    return AttachmentProcessor(is_premium=True)


@pytest.mark.asyncio
async def test_no_attachments(processor):
    """Test processing task with no attachments."""
    result = await processor.process_attachments([], "card-123", "task-456")

    assert result["success_count"] == 0
    assert result["failed_count"] == 0
    assert result["skipped_count"] == 0
    assert result["oversized_files"] == []


@pytest.mark.asyncio
async def test_oversized_attachment_free_plan(processor):
    """Test that oversized attachments are skipped on free plan."""
    attachments = [
        {
            "name": "large-file.zip",
            "size": 15 * 1024 * 1024,  # 15MB, exceeds 10MB limit
            "download_url": "https://example.com/file.zip",
            "mime_type": "application/zip",
        }
    ]

    with patch.object(
        processor.trello_client, "append_card_description", new_callable=AsyncMock
    ) as mock_append:
        result = await processor.process_attachments(
            attachments, "card-123", "task-456"
        )

        assert result["success_count"] == 0
        assert result["skipped_count"] == 1
        assert "large-file.zip" in result["oversized_files"]
        mock_append.assert_called_once()


@pytest.mark.asyncio
async def test_oversized_attachment_premium_plan(processor_premium):
    """Test that larger files are allowed on premium plan."""
    attachments = [
        {
            "name": "large-file.zip",
            "size": 15 * 1024 * 1024,  # 15MB, within 250MB limit
            "download_url": "https://example.com/file.zip",
            "mime_type": "application/zip",
        }
    ]

    with patch.object(
        processor_premium, "_download_attachment", new_callable=AsyncMock
    ) as mock_download, patch.object(
        processor_premium.trello_client, "upload_attachment", new_callable=AsyncMock
    ) as mock_upload:
        mock_download.return_value = b"file content"
        mock_upload.return_value = True

        result = await processor_premium.process_attachments(
            attachments, "card-123", "task-456"
        )

        assert result["success_count"] == 1
        assert result["skipped_count"] == 0


@pytest.mark.asyncio
async def test_attachment_missing_download_url(processor):
    """Test handling attachment without download URL."""
    attachments = [
        {
            "name": "file.txt",
            "size": 1024,
            "download_url": None,
            "mime_type": "text/plain",
        }
    ]

    result = await processor.process_attachments(attachments, "card-123", "task-456")

    assert result["success_count"] == 0
    assert result["failed_count"] == 1


@pytest.mark.asyncio
async def test_successful_attachment_upload(processor):
    """Test successful attachment download and upload."""
    attachments = [
        {
            "name": "document.pdf",
            "size": 2 * 1024 * 1024,  # 2MB
            "download_url": "https://example.com/doc.pdf",
            "mime_type": "application/pdf",
        }
    ]

    with patch.object(
        processor, "_download_attachment", new_callable=AsyncMock
    ) as mock_download, patch.object(
        processor.trello_client, "upload_attachment", new_callable=AsyncMock
    ) as mock_upload:
        mock_download.return_value = b"pdf content"
        mock_upload.return_value = True

        result = await processor.process_attachments(
            attachments, "card-123", "task-456"
        )

        assert result["success_count"] == 1
        assert result["failed_count"] == 0
        mock_download.assert_called_once_with("https://example.com/doc.pdf")
        mock_upload.assert_called_once()


@pytest.mark.asyncio
async def test_attachment_upload_failure_continues_processing(processor):
    """Test that attachment upload failure doesn't abort remaining attachments."""
    attachments = [
        {
            "name": "file1.txt",
            "size": 1024,
            "download_url": "https://example.com/file1.txt",
            "mime_type": "text/plain",
        },
        {
            "name": "file2.txt",
            "size": 1024,
            "download_url": "https://example.com/file2.txt",
            "mime_type": "text/plain",
        },
    ]

    with patch.object(
        processor, "_download_attachment", new_callable=AsyncMock
    ) as mock_download, patch.object(
        processor.trello_client, "upload_attachment", new_callable=AsyncMock
    ) as mock_upload:
        mock_download.return_value = b"content"
        # First upload fails, second succeeds
        mock_upload.side_effect = [Exception("Upload failed"), True]

        result = await processor.process_attachments(
            attachments, "card-123", "task-456"
        )

        assert result["success_count"] == 1
        assert result["failed_count"] == 1
        assert mock_upload.call_count == 2  # Both attempted


@pytest.mark.asyncio
async def test_multiple_oversized_files_notice(processor):
    """Test that notice includes all oversized files."""
    attachments = [
        {
            "name": "large1.zip",
            "size": 15 * 1024 * 1024,
            "download_url": "https://example.com/large1.zip",
            "mime_type": "application/zip",
        },
        {
            "name": "large2.iso",
            "size": 20 * 1024 * 1024,
            "download_url": "https://example.com/large2.iso",
            "mime_type": "application/octet-stream",
        },
    ]

    with patch.object(
        processor.trello_client, "append_card_description", new_callable=AsyncMock
    ) as mock_append:
        result = await processor.process_attachments(
            attachments, "card-123", "task-456"
        )

        assert result["skipped_count"] == 2
        assert "large1.zip" in result["oversized_files"]
        assert "large2.iso" in result["oversized_files"]

        # Check that notice was appended
        mock_append.assert_called_once()
        call_args = mock_append.call_args
        notice = call_args[0][1]
        assert "large1.zip" in notice
        assert "large2.iso" in notice
