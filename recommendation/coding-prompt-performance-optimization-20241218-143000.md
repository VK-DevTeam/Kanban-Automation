# Coding Prompt: Performance Optimization

**Category**: Performance  
**Priority**: High  
**Files Affected**: `app/worker/asana_client.py`, `app/worker/trello_client.py`, `app/worker/attachments.py`, `app/queue/redis_queue.py`

## Issue Description
The current implementation has several performance bottlenecks that impact scalability and response times. Key issues include lack of HTTP connection pooling, inefficient memory usage for large files, and synchronous operations in async contexts.

## Current Performance Issues
1. **HTTP Connection Management**: New HTTP client created for each request
2. **Memory Usage**: Large attachments loaded entirely into memory
3. **Async/Sync Mixing**: Synchronous Redis operations in async context
4. **Missing Caching**: No caching for repeated API calls
5. **Inefficient Retry Logic**: Fixed delays without exponential backoff optimization

## Target Implementation

### 1. Implement HTTP Connection Pooling

**File**: `app/worker/asana_client.py` (Lines 15-40)
**Current Code**:
```python
class AsanaClient:
    def __init__(self):
        settings = get_settings()
        self.access_token = settings.asana_access_token
        self.timeout = settings.api_timeout_seconds

    async def get_task(self, task_gid: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Creates new connection for each request
```

**Target Implementation**:
```python
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, AsyncGenerator
import httpx
from cachetools import TTLCache
import time

class OptimizedAsanaClient:
    """High-performance Asana client with connection pooling and caching."""
    
    BASE_URL: str = "https://app.asana.com/api/1.0"
    
    def __init__(self) -> None:
        settings: Settings = get_settings()
        self.access_token: str = settings.asana_access_token
        self.timeout: int = settings.api_timeout_seconds
        self.max_retries: int = settings.max_retry_attempts
        self.logger = get_logger(__name__)
        
        # HTTP client with connection pooling
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        
        # Response caching
        self._cache: TTLCache = TTLCache(maxsize=1000, ttl=300)  # 5 minute TTL
        self._cache_lock = asyncio.Lock()
        
        # Connection pool configuration
        self._limits = httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0
        )
        
        # Timeout configuration
        self._timeout = httpx.Timeout(
            connect=10.0,
            read=self.timeout,
            write=10.0,
            pool=5.0
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            async with self._client_lock:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        limits=self._limits,
                        timeout=self._timeout,
                        headers=self._get_headers(),
                        follow_redirects=True
                    )
        return self._client

    async def close(self) -> None:
        """Close HTTP client and cleanup resources."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_cache_key(self, method: str, url: str, params: Optional[Dict] = None) -> str:
        """Generate cache key for request."""
        key_parts = [method, url]
        if params:
            sorted_params = sorted(params.items())
            key_parts.append(str(sorted_params))
        return "|".join(key_parts)

    async def _cached_request(
        self, 
        method: str, 
        url: str, 
        params: Optional[Dict] = None,
        cache_ttl: int = 300
    ) -> Optional[Dict[str, Any]]:
        """Make cached HTTP request."""
        cache_key = self._get_cache_key(method, url, params)
        
        # Check cache first
        async with self._cache_lock:
            if cache_key in self._cache:
                self.logger.debug("Cache hit", cache_key=cache_key)
                return self._cache[cache_key]

        # Make request
        client = await self._get_client()
        
        try:
            response = await client.request(method, url, params=params)
            
            # Handle common error cases
            if response.status_code == 404:
                return None
            elif response.status_code in (401, 403):
                self.logger.error("Authentication/authorization error", status=response.status_code)
                raise AuthenticationError(f"API error: {response.status_code}")
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "60"))
                self.logger.warning("Rate limited", retry_after=retry_after)
                raise RateLimitError(f"Rate limited, retry after {retry_after}s")
            
            response.raise_for_status()
            data = response.json()
            result = data.get("data")
            
            # Cache successful responses
            if result and cache_ttl > 0:
                async with self._cache_lock:
                    self._cache[cache_key] = result
            
            return result
            
        except httpx.HTTPError as e:
            self.logger.error("HTTP error", error=str(e), url=url)
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, RateLimitError)),
    )
    async def get_task(self, task_gid: str) -> Optional[Dict[str, Any]]:
        """Fetch task with caching and connection pooling."""
        url = f"{self.BASE_URL}/tasks/{task_gid}"
        params = {
            "opt_fields": "name,notes,attachments.name,attachments.download_url,attachments.size,attachments.mime_type"
        }
        
        return await self._cached_request("GET", url, params, cache_ttl=300)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, RateLimitError)),
    )
    async def get_section(self, section_gid: str) -> Optional[str]:
        """Fetch section name with caching."""
        url = f"{self.BASE_URL}/sections/{section_gid}"
        params = {"opt_fields": "name"}
        
        result = await self._cached_request("GET", url, params, cache_ttl=600)  # Longer cache for sections
        return result.get("name") if result else None

# Context manager for client lifecycle
@asynccontextmanager
async def asana_client() -> AsyncGenerator[OptimizedAsanaClient, None]:
    """Context manager for Asana client with proper cleanup."""
    client = OptimizedAsanaClient()
    try:
        yield client
    finally:
        await client.close()
```

### 2. Optimize Redis Operations for Async Context

**File**: `app/queue/redis_queue.py` (Lines 1-30)
**Current Code**:
```python
import redis

class RedisQueue:
    def __init__(self):
        settings = get_settings()
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
```

**Target Implementation**:
```python
import asyncio
from typing import Optional, Dict, Any
import redis.asyncio as redis
from redis.asyncio import ConnectionPool
import json
import time

class OptimizedRedisQueue:
    """High-performance Redis queue with async operations and connection pooling."""
    
    QUEUE_KEY = "asana_trello:queue"
    DLQ_KEY = "asana_trello:dlq"
    DEDUP_KEY = "asana_trello:dedup:events"
    
    def __init__(self) -> None:
        settings = get_settings()
        self.logger = get_logger(__name__)
        
        # Connection pool for better performance
        self._pool = ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
            retry_on_timeout=True,
            socket_keepalive=True,
            socket_keepalive_options={},
            health_check_interval=30
        )
        
        self._redis: Optional[redis.Redis] = None
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> redis.Redis:
        """Get Redis client with connection pooling."""
        if self._redis is None:
            async with self._lock:
                if self._redis is None:
                    self._redis = redis.Redis(connection_pool=self._pool)
        return self._redis

    async def close(self) -> None:
        """Close Redis connections."""
        if self._redis:
            await self._redis.close()
        await self._pool.disconnect()

    async def enqueue(self, event: Dict[str, Any]) -> bool:
        """Enqueue event with async Redis operations."""
        try:
            redis_client = await self._get_redis()
            event_json = json.dumps(event)
            
            # Use pipeline for better performance
            async with redis_client.pipeline() as pipe:
                await pipe.lpush(self.QUEUE_KEY, event_json)
                await pipe.execute()
            
            self.logger.info("Event enqueued", event_id=event.get("id"))
            return True
            
        except Exception as e:
            self.logger.error("Failed to enqueue event", error=str(e), event_id=event.get("id"))
            return False

    async def dequeue(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """Dequeue event with async Redis operations."""
        try:
            redis_client = await self._get_redis()
            result = await redis_client.brpop(self.QUEUE_KEY, timeout=timeout)
            
            if result:
                _, event_json = result
                event = json.loads(event_json)
                self.logger.info("Event dequeued", event_id=event.get("id"))
                return event
            return None
            
        except Exception as e:
            self.logger.error("Failed to dequeue event", error=str(e))
            return None

    async def push_to_dlq_batch(self, events: List[Dict[str, Any]], failure_reason: str) -> bool:
        """Push multiple events to DLQ in batch for better performance."""
        try:
            redis_client = await self._get_redis()
            timestamp = int(time.time())
            
            # Prepare batch data
            dlq_records = []
            for event in events:
                dlq_record = {
                    "event": event,
                    "failure_reason": failure_reason,
                    "timestamp": timestamp,
                }
                dlq_records.append(json.dumps(dlq_record))
            
            # Batch insert
            if dlq_records:
                async with redis_client.pipeline() as pipe:
                    for record in dlq_records:
                        await pipe.lpush(self.DLQ_KEY, record)
                    await pipe.execute()
            
            self.logger.info("Events pushed to DLQ", count=len(events), reason=failure_reason)
            return True
            
        except Exception as e:
            self.logger.error("Failed to push events to DLQ", error=str(e))
            return False

    async def mark_events_deduped_batch(self, event_ids: List[str]) -> bool:
        """Mark multiple events as deduped in batch."""
        try:
            redis_client = await self._get_redis()
            
            # Batch operation
            async with redis_client.pipeline() as pipe:
                for event_id in event_ids:
                    key = f"{self.DEDUP_KEY}:{event_id}"
                    await pipe.setex(key, 86400, "1")  # 24 hour TTL
                await pipe.execute()
            
            return True
            
        except Exception as e:
            self.logger.error("Failed to mark events as deduped", error=str(e))
            return False

    async def get_queue_stats(self) -> Dict[str, int]:
        """Get queue statistics efficiently."""
        try:
            redis_client = await self._get_redis()
            
            # Use pipeline for multiple operations
            async with redis_client.pipeline() as pipe:
                await pipe.llen(self.QUEUE_KEY)
                await pipe.llen(self.DLQ_KEY)
                results = await pipe.execute()
            
            return {
                "queue_size": results[0],
                "dlq_size": results[1]
            }
            
        except Exception as e:
            self.logger.error("Failed to get queue stats", error=str(e))
            return {"queue_size": 0, "dlq_size": 0}
```

### 3. Optimize Attachment Processing with Streaming

**File**: `app/worker/attachments.py` (Lines 100-150)
**Current Code**:
```python
async def _download_attachment(self, download_url: str) -> bytes:
    async with httpx.AsyncClient(timeout=self.attachment_timeout) as client:
        response = await client.get(download_url, follow_redirects=True)
        response.raise_for_status()
        return response.content  # Loads entire file into memory
```

**Target Implementation**:
```python
import asyncio
import tempfile
import aiofiles
from pathlib import Path
from typing import AsyncGenerator, BinaryIO

class StreamingAttachmentProcessor:
    """Memory-efficient attachment processor with streaming."""
    
    CHUNK_SIZE = 8192  # 8KB chunks
    MAX_CONCURRENT_DOWNLOADS = 3
    
    def __init__(self, is_premium: bool = False):
        settings = get_settings()
        self.attachment_timeout = settings.attachment_timeout_seconds
        self.trello_client = TrelloClient()
        self.logger = get_logger(__name__)
        self.size_limit = self.TRELLO_PREMIUM_LIMIT if is_premium else self.TRELLO_FREE_LIMIT
        
        # Semaphore for concurrent download control
        self._download_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_DOWNLOADS)

    async def _stream_download(
        self, 
        download_url: str, 
        expected_size: int
    ) -> AsyncGenerator[bytes, None]:
        """Stream download attachment in chunks."""
        
        async with self._download_semaphore:  # Limit concurrent downloads
            async with httpx.AsyncClient(
                timeout=self.attachment_timeout,
                limits=httpx.Limits(max_connections=5)
            ) as client:
                
                downloaded_size = 0
                
                async with client.stream('GET', download_url, follow_redirects=True) as response:
                    response.raise_for_status()
                    
                    # Validate content length
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > self.size_limit:
                        raise ValueError("Attachment exceeds size limit")
                    
                    async for chunk in response.aiter_bytes(chunk_size=self.CHUNK_SIZE):
                        downloaded_size += len(chunk)
                        if downloaded_size > self.size_limit:
                            raise ValueError("Attachment exceeds size limit during download")
                        yield chunk

    async def _process_attachment_streaming(
        self,
        attachment: Dict[str, Any],
        card_id: str,
        task_gid: str,
    ) -> Dict[str, Any]:
        """Process attachment with streaming to minimize memory usage."""
        
        filename = attachment.get("name", "attachment")
        size = attachment.get("size", 0)
        download_url = attachment.get("download_url")
        mime_type = attachment.get("mime_type", "application/octet-stream")

        # Pre-flight checks
        if size > self.size_limit:
            return {"status": "oversized", "filename": filename}

        if not download_url:
            return {"status": "failed", "filename": filename}

        try:
            # Use temporary file for large attachments
            if size > 10 * 1024 * 1024:  # 10MB threshold
                return await self._process_large_attachment(
                    download_url, filename, mime_type, card_id, task_gid, size
                )
            else:
                return await self._process_small_attachment(
                    download_url, filename, mime_type, card_id, task_gid, size
                )
                
        except Exception as e:
            self.logger.error("Failed to process attachment", error=str(e), filename=filename)
            return {"status": "failed", "filename": filename}

    async def _process_large_attachment(
        self,
        download_url: str,
        filename: str,
        mime_type: str,
        card_id: str,
        task_gid: str,
        expected_size: int
    ) -> Dict[str, Any]:
        """Process large attachment using temporary file."""
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        
        try:
            # Stream download to temporary file
            async with aiofiles.open(temp_path, 'wb') as f:
                async for chunk in self._stream_download(download_url, expected_size):
                    await f.write(chunk)
            
            # Upload from temporary file
            async with aiofiles.open(temp_path, 'rb') as f:
                file_content = await f.read()
                await self.trello_client.upload_attachment(
                    card_id, filename, file_content, mime_type
                )
            
            self.logger.info("Large attachment processed", filename=filename, size=expected_size)
            return {"status": "success", "filename": filename}
            
        finally:
            # Cleanup temporary file
            try:
                temp_path.unlink()
            except Exception as e:
                self.logger.warning("Failed to cleanup temp file", error=str(e))

    async def _process_small_attachment(
        self,
        download_url: str,
        filename: str,
        mime_type: str,
        card_id: str,
        task_gid: str,
        expected_size: int
    ) -> Dict[str, Any]:
        """Process small attachment in memory."""
        
        content = bytearray()
        async for chunk in self._stream_download(download_url, expected_size):
            content.extend(chunk)
        
        await self.trello_client.upload_attachment(
            card_id, filename, bytes(content), mime_type
        )
        
        self.logger.info("Small attachment processed", filename=filename, size=len(content))
        return {"status": "success", "filename": filename}

    async def process_attachments_concurrent(
        self,
        attachments: List[Dict[str, Any]],
        card_id: str,
        task_gid: str,
    ) -> Dict[str, Any]:
        """Process multiple attachments concurrently."""
        
        if not attachments:
            return {"success_count": 0, "failed_count": 0, "skipped_count": 0}

        # Process attachments concurrently
        tasks = [
            self._process_attachment_streaming(attachment, card_id, task_gid)
            for attachment in attachments
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Aggregate results
        success_count = 0
        failed_count = 0
        skipped_count = 0
        oversized_files = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed_count += 1
                self.logger.error("Attachment processing exception", error=str(result))
            elif result["status"] == "success":
                success_count += 1
            elif result["status"] == "oversized":
                skipped_count += 1
                oversized_files.append(result["filename"])
            else:
                failed_count += 1

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "oversized_files": oversized_files,
        }
```

### 4. Add Performance Monitoring

**File**: `app/observability/metrics.py` (New File)
**Target Implementation**:
```python
"""Performance monitoring and metrics collection."""

import time
import asyncio
from typing import Dict, Any, Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from collections import defaultdict, deque
import statistics

@dataclass
class PerformanceMetrics:
    """Performance metrics container."""
    request_count: int = 0
    total_duration: float = 0.0
    min_duration: float = float('inf')
    max_duration: float = 0.0
    recent_durations: deque = field(default_factory=lambda: deque(maxlen=100))
    error_count: int = 0

class PerformanceMonitor:
    """Performance monitoring with metrics collection."""
    
    def __init__(self):
        self.metrics: Dict[str, PerformanceMetrics] = defaultdict(PerformanceMetrics)
        self.logger = get_logger(__name__)

    @asynccontextmanager
    async def measure(self, operation_name: str):
        """Context manager to measure operation performance."""
        start_time = time.time()
        error_occurred = False
        
        try:
            yield
        except Exception as e:
            error_occurred = True
            raise
        finally:
            duration = time.time() - start_time
            self._record_metric(operation_name, duration, error_occurred)

    def _record_metric(self, operation_name: str, duration: float, error: bool = False):
        """Record performance metric."""
        metric = self.metrics[operation_name]
        
        metric.request_count += 1
        metric.total_duration += duration
        metric.min_duration = min(metric.min_duration, duration)
        metric.max_duration = max(metric.max_duration, duration)
        metric.recent_durations.append(duration)
        
        if error:
            metric.error_count += 1

    def get_stats(self, operation_name: str) -> Dict[str, Any]:
        """Get performance statistics for operation."""
        metric = self.metrics.get(operation_name)
        if not metric or metric.request_count == 0:
            return {}

        recent_durations = list(metric.recent_durations)
        
        return {
            "request_count": metric.request_count,
            "error_count": metric.error_count,
            "error_rate": metric.error_count / metric.request_count,
            "avg_duration": metric.total_duration / metric.request_count,
            "min_duration": metric.min_duration,
            "max_duration": metric.max_duration,
            "p50_duration": statistics.median(recent_durations) if recent_durations else 0,
            "p95_duration": statistics.quantiles(recent_durations, n=20)[18] if len(recent_durations) > 10 else 0,
        }

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get all performance statistics."""
        return {name: self.get_stats(name) for name in self.metrics.keys()}

# Global performance monitor instance
performance_monitor = PerformanceMonitor()
```

## Implementation Instructions

1. **Install Performance Dependencies**:
   ```bash
   pip install redis[hiredis] aiofiles cachetools
   ```

2. **Update HTTP Clients**: Replace synchronous HTTP clients with optimized async versions
3. **Implement Connection Pooling**: Configure connection pools for HTTP and Redis clients
4. **Add Response Caching**: Implement TTL-based caching for API responses
5. **Optimize File Processing**: Use streaming for large file downloads
6. **Add Performance Monitoring**: Implement metrics collection for all operations
7. **Configure Async Redis**: Replace sync Redis client with async version
8. **Batch Operations**: Implement batch processing where applicable

## Success Criteria
- [ ] HTTP connection pooling reduces connection overhead by 80%
- [ ] Memory usage for large attachments reduced by 90%
- [ ] All Redis operations are async
- [ ] Response caching reduces API calls by 50%
- [ ] Concurrent attachment processing improves throughput by 3x
- [ ] Performance metrics available for all operations
- [ ] No blocking operations in async context
- [ ] Resource cleanup properly implemented

## Related Files
- `app/config.py` - Add performance configuration settings
- `app/main.py` - Add performance monitoring middleware
- `requirements.txt` - Add performance dependencies
- `tests/test_performance.py` - Create performance test suite

## Rationale
Performance optimizations provide:
- **Scalability**: Handle higher throughput with same resources
- **Resource Efficiency**: Reduce memory and CPU usage
- **Response Times**: Faster processing and lower latency
- **Cost Reduction**: Better resource utilization reduces infrastructure costs
- **User Experience**: Improved responsiveness and reliability

These optimizations are essential for production scalability and efficient resource utilization.