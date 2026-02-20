# Coding Prompt: Type Safety - Worker Module

**Category**: Type Safety  
**Priority**: Critical  
**Files Affected**: `app/worker/processor.py`, `app/worker/worker.py`, `app/worker/asana_client.py`, `app/worker/trello_client.py`, `app/worker/deduplication.py`, `app/worker/attachments.py`

## Issue Description
The worker module lacks comprehensive type hints, making the code difficult to maintain, debug, and understand. Missing type annotations affect IDE support, runtime safety, and documentation quality.

## Current Code Issues
- 90% of functions missing type hints for parameters and return types
- No use of `typing.Protocol` for client interfaces
- Missing generic type annotations for collections
- Inconsistent Optional/Union type usage

## Target Implementation

### 1. Add Type Hints to EventProcessor (`app/worker/processor.py`)

**Current Code** (Lines 1-25):
```python
class EventProcessor:
    """Core orchestrator for processing Asana events."""

    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        # ... other initializations

    async def process_event(self, event: Dict[str, Any]) -> bool:
        # Missing detailed type hints for internal variables
```

**Target Implementation**:
```python
from typing import Dict, Any, Optional, Protocol, List
from abc import ABC, abstractmethod

class AsanaClientProtocol(Protocol):
    async def get_task(self, task_gid: str) -> Optional[Dict[str, Any]]: ...
    async def get_section(self, section_gid: str) -> Optional[str]: ...

class TrelloClientProtocol(Protocol):
    async def create_card(self, name: str, description: str, list_id: str) -> Optional[str]: ...

class EventProcessor:
    """Core orchestrator for processing Asana events."""

    def __init__(
        self,
        asana_client: Optional[AsanaClientProtocol] = None,
        trello_client: Optional[TrelloClientProtocol] = None,
    ) -> None:
        self.settings: Settings = get_settings()
        self.logger: structlog.BoundLogger = get_logger(__name__)
        self.queue: RedisQueue = RedisQueue()
        self.dedup: Deduplication = Deduplication()
        self.asana_client: AsanaClientProtocol = asana_client or AsanaClient()
        self.trello_client: TrelloClientProtocol = trello_client or TrelloClient()

    async def process_event(self, event: Dict[str, Any]) -> bool:
        """Process a single Asana event with full type safety."""
        event_id: Optional[str] = event.get("id")
        start_time: float = time.time()
        
        # Add type hints for all local variables
        resource: Dict[str, Any] = event.get("resource", {})
        task_gid: Optional[str] = resource.get("gid")
        section_gid: Optional[str] = event.get("data", {}).get("new_section", {}).get("gid")
        
        # ... rest of implementation with proper typing
```

### 2. Add Type Hints to API Clients

**File**: `app/worker/asana_client.py` (Lines 15-30)
**Current Code**:
```python
class AsanaClient:
    def __init__(self):
        settings = get_settings()
        self.access_token = settings.asana_access_token
        # ... other initializations
```

**Target Implementation**:
```python
from typing import Dict, Any, Optional, List, Union
import httpx
from structlog import BoundLogger

class AsanaClient:
    """Asana REST API client with comprehensive type safety."""
    
    BASE_URL: str = "https://app.asana.com/api/1.0"
    
    def __init__(self) -> None:
        settings: Settings = get_settings()
        self.access_token: str = settings.asana_access_token
        self.timeout: int = settings.api_timeout_seconds
        self.max_retries: int = settings.max_retry_attempts
        self.logger: BoundLogger = get_logger(__name__)

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers with proper typing."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def get_task(self, task_gid: str) -> Optional[Dict[str, Any]]:
        """Fetch task details with comprehensive type hints."""
        # Implementation with proper error handling types
```

### 3. Add Type Hints to Deduplication Module

**File**: `app/worker/deduplication.py` (Lines 1-20)
**Target Implementation**:
```python
import json
import time
from typing import Optional, Dict, Any, Union
import redis
from redis import Redis
from structlog import BoundLogger

class Deduplication:
    """Distributed lock and mapping store with full type safety."""

    LOCK_PREFIX: str = "asana_trello:lock:task:"
    MAPPING_KEY: str = "asana_trello:task_card_map"
    LOCK_TIMEOUT: int = 60  # seconds

    def __init__(self) -> None:
        settings: Settings = get_settings()
        self.redis_client: Redis[str] = redis.from_url(settings.redis_url, decode_responses=True)
        self.logger: BoundLogger = get_logger(__name__)

    def acquire_lock(self, task_gid: str) -> bool:
        """Acquire distributed lock with proper return type annotation."""
        # Implementation with typed variables
```

## Implementation Instructions

1. **Install Type Checking Tools**:
   ```bash
   pip install mypy types-redis
   ```

2. **Add Type Imports**: Update all worker module files to import necessary typing components:
   ```python
   from typing import Dict, Any, Optional, List, Union, Protocol
   from abc import ABC, abstractmethod
   ```

3. **Create Protocol Interfaces**: Define protocols for external service clients to enable dependency injection and testing.

4. **Add Comprehensive Type Hints**: 
   - All function parameters and return types
   - Class attributes and instance variables
   - Local variables where type inference is unclear
   - Generic types for collections (List[str], Dict[str, Any])

5. **Configure MyPy**: Create `mypy.ini` configuration:
   ```ini
   [mypy]
   python_version = 3.10
   warn_return_any = True
   warn_unused_configs = True
   disallow_untyped_defs = True
   ```

6. **Validation**: Run type checking:
   ```bash
   mypy app/worker/
   ```

## Success Criteria
- [ ] All functions have complete type annotations
- [ ] MyPy passes with no errors on strict mode
- [ ] Protocol interfaces defined for external dependencies
- [ ] Generic types used appropriately for collections
- [ ] Optional/Union types used consistently
- [ ] IDE provides full autocomplete and error detection

## Related Files
- `app/config.py` - Update Settings type annotations
- `app/observability/logger.py` - Add logger type hints
- `app/queue/redis_queue.py` - Add queue type annotations

## Rationale
Type hints provide:
- **IDE Support**: Better autocomplete, refactoring, and error detection
- **Documentation**: Self-documenting code that's easier to understand
- **Runtime Safety**: Early detection of type-related bugs
- **Maintainability**: Easier to modify and extend code safely
- **Testing**: Better test coverage through type-aware testing tools

This change is foundational for all other improvements and should be implemented first.