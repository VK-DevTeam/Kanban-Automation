# Coding Prompt: Architecture - SOLID Principles Violations

**Category**: Architecture  
**Priority**: Critical  
**Files Affected**: `app/worker/processor.py`, `app/worker/worker.py`, `app/main.py`

## Issue Description
The current architecture violates multiple SOLID principles, making the code difficult to test, extend, and maintain. The `EventProcessor` class has too many responsibilities, and there's tight coupling between components.

## Current Code Issues
- **Single Responsibility Principle**: `EventProcessor` handles validation, API calls, deduplication, error handling, and business logic
- **Dependency Inversion**: Direct instantiation of concrete classes instead of dependency injection
- **Open/Closed Principle**: Hard to extend without modifying existing code
- **Interface Segregation**: No interfaces defined for external services

## Target Implementation

### 1. Refactor EventProcessor to Follow Single Responsibility Principle

**File**: `app/worker/processor.py` (Lines 15-50)
**Current Code**:
```python
class EventProcessor:
    """Core orchestrator for processing Asana events."""

    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger(__name__)
        self.queue = RedisQueue()
        self.dedup = Deduplication()
        self.asana_client = AsanaClient()
        self.trello_client = TrelloClient()

    async def process_event(self, event: Dict[str, Any]) -> bool:
        # 200+ lines of mixed responsibilities
```

**Target Implementation**:
```python
from abc import ABC, abstractmethod
from typing import Protocol, Dict, Any, Optional
from dataclasses import dataclass

# Domain Models
@dataclass
class TaskData:
    gid: str
    name: str
    notes: str
    attachments: List[Dict[str, Any]]

@dataclass
class ProcessingResult:
    success: bool
    card_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

# Service Interfaces
class EventValidatorProtocol(Protocol):
    def validate_event(self, event: Dict[str, Any]) -> Optional[str]: ...
    def extract_task_info(self, event: Dict[str, Any]) -> Optional[Tuple[str, str]]: ...

class TaskServiceProtocol(Protocol):
    async def get_task_data(self, task_gid: str) -> Optional[TaskData]: ...
    async def get_section_name(self, section_gid: str) -> Optional[str]: ...

class CardServiceProtocol(Protocol):
    async def create_card_from_task(self, task_data: TaskData, list_id: str) -> Optional[str]: ...

class DeduplicationServiceProtocol(Protocol):
    def acquire_lock(self, task_gid: str) -> bool: ...
    def release_lock(self, task_gid: str) -> None: ...
    def is_already_processed(self, task_gid: str) -> bool: ...
    def mark_as_processed(self, task_gid: str, card_id: str, event_id: str) -> None: ...

# Single Responsibility Classes
class EventValidator:
    """Validates and extracts information from Asana events."""
    
    def __init__(self, trigger_section_name: str) -> None:
        self.trigger_section_name = trigger_section_name
        self.logger = get_logger(__name__)

    def validate_event(self, event: Dict[str, Any]) -> Optional[str]:
        """Validate event structure and return error message if invalid."""
        if not self._is_section_changed_event(event):
            return "Not a section_changed event"
        return None

    def extract_task_info(self, event: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """Extract task_gid and section_gid from event."""
        resource = event.get("resource", {})
        task_gid = resource.get("gid")
        section_gid = event.get("data", {}).get("new_section", {}).get("gid")
        
        if not task_gid or not section_gid:
            return None
        return task_gid, section_gid

class TaskService:
    """Service for fetching task data from Asana."""
    
    def __init__(self, asana_client: AsanaClientProtocol) -> None:
        self.asana_client = asana_client
        self.logger = get_logger(__name__)

    async def get_task_data(self, task_gid: str) -> Optional[TaskData]:
        """Fetch and transform task data."""
        raw_task = await self.asana_client.get_task(task_gid)
        if not raw_task:
            return None
        
        return TaskData(
            gid=task_gid,
            name=raw_task.get("name", ""),
            notes=raw_task.get("notes", ""),
            attachments=raw_task.get("attachments", [])
        )

    async def get_section_name(self, section_gid: str) -> Optional[str]:
        """Get section name from Asana."""
        return await self.asana_client.get_section(section_gid)

class CardService:
    """Service for creating cards in Trello."""
    
    def __init__(self, trello_client: TrelloClientProtocol, attachment_processor: AttachmentProcessor) -> None:
        self.trello_client = trello_client
        self.attachment_processor = attachment_processor
        self.logger = get_logger(__name__)

    async def create_card_from_task(self, task_data: TaskData, list_id: str) -> Optional[str]:
        """Create Trello card with attachments from task data."""
        card_id = await self.trello_client.create_card(
            name=task_data.name,
            description=task_data.notes,
            list_id=list_id
        )
        
        if not card_id:
            return None

        # Process attachments
        if task_data.attachments:
            await self.attachment_processor.process_attachments(
                task_data.attachments, card_id, task_data.gid
            )
        
        return card_id

# Refactored EventProcessor with Single Responsibility
class EventProcessor:
    """Orchestrates event processing using injected services."""

    def __init__(
        self,
        validator: EventValidatorProtocol,
        task_service: TaskServiceProtocol,
        card_service: CardServiceProtocol,
        dedup_service: DeduplicationServiceProtocol,
        settings: Settings,
    ) -> None:
        self.validator = validator
        self.task_service = task_service
        self.card_service = card_service
        self.dedup_service = dedup_service
        self.settings = settings
        self.logger = get_logger(__name__)

    async def process_event(self, event: Dict[str, Any]) -> ProcessingResult:
        """Process event using injected services."""
        event_id = event.get("id")
        
        # Step 1: Validate event
        validation_error = self.validator.validate_event(event)
        if validation_error:
            self.logger.info("Event filtered", reason=validation_error, event_id=event_id)
            return ProcessingResult(success=True)  # Not an error, just filtered

        # Step 2: Extract task information
        task_info = self.validator.extract_task_info(event)
        if not task_info:
            return ProcessingResult(
                success=False,
                error_code="INVALID_EVENT_STRUCTURE",
                error_message="Missing task_gid or section_gid"
            )

        task_gid, section_gid = task_info

        # Step 3: Validate section
        section_name = await self.task_service.get_section_name(section_gid)
        if section_name != self.settings.asana_trigger_section_name:
            self.logger.info("Event filtered", reason="Section mismatch", event_id=event_id)
            return ProcessingResult(success=True)

        # Step 4: Handle deduplication with lock
        if not self.dedup_service.acquire_lock(task_gid):
            self.logger.info("Lock not acquired", task_gid=task_gid, event_id=event_id)
            return ProcessingResult(success=True)

        try:
            if self.dedup_service.is_already_processed(task_gid):
                self.logger.info("Already processed", task_gid=task_gid, event_id=event_id)
                return ProcessingResult(success=True)

            # Step 5: Get task data
            task_data = await self.task_service.get_task_data(task_gid)
            if not task_data:
                return ProcessingResult(
                    success=False,
                    error_code="TASK_NOT_FOUND",
                    error_message="Task not found in Asana"
                )

            # Step 6: Create card
            card_id = await self.card_service.create_card_from_task(
                task_data, self.settings.trello_target_list_id
            )
            if not card_id:
                return ProcessingResult(
                    success=False,
                    error_code="CARD_CREATION_FAILED",
                    error_message="Failed to create Trello card"
                )

            # Step 7: Mark as processed
            self.dedup_service.mark_as_processed(task_gid, card_id, event_id)

            return ProcessingResult(success=True, card_id=card_id)

        finally:
            self.dedup_service.release_lock(task_gid)
```

### 2. Implement Dependency Injection Container

**File**: `app/container.py` (New File)
**Target Implementation**:
```python
from typing import Dict, Any, Callable, TypeVar, Type
from dataclasses import dataclass

T = TypeVar('T')

@dataclass
class ServiceDefinition:
    factory: Callable[[], Any]
    singleton: bool = True
    instance: Any = None

class DIContainer:
    """Simple dependency injection container."""
    
    def __init__(self) -> None:
        self._services: Dict[Type, ServiceDefinition] = {}
    
    def register(self, interface: Type[T], factory: Callable[[], T], singleton: bool = True) -> None:
        """Register a service factory."""
        self._services[interface] = ServiceDefinition(factory, singleton)
    
    def get(self, interface: Type[T]) -> T:
        """Get service instance."""
        service_def = self._services.get(interface)
        if not service_def:
            raise ValueError(f"Service {interface} not registered")
        
        if service_def.singleton:
            if service_def.instance is None:
                service_def.instance = service_def.factory()
            return service_def.instance
        
        return service_def.factory()

# Service Registration
def create_container() -> DIContainer:
    """Create and configure the DI container."""
    container = DIContainer()
    
    # Register services
    container.register(AsanaClientProtocol, lambda: AsanaClient())
    container.register(TrelloClientProtocol, lambda: TrelloClient())
    container.register(
        EventValidatorProtocol, 
        lambda: EventValidator(get_settings().asana_trigger_section_name)
    )
    container.register(
        TaskServiceProtocol,
        lambda: TaskService(container.get(AsanaClientProtocol))
    )
    container.register(
        CardServiceProtocol,
        lambda: CardService(
            container.get(TrelloClientProtocol),
            AttachmentProcessor()
        )
    )
    container.register(DeduplicationServiceProtocol, lambda: Deduplication())
    
    return container
```

### 3. Update Worker to Use Dependency Injection

**File**: `app/worker/worker.py` (Lines 10-25)
**Target Implementation**:
```python
from app.container import create_container
from app.worker.processor import EventProcessor

async def worker_loop() -> None:
    """Main consumer loop with dependency injection."""
    setup_logging()
    logger = get_logger(__name__)
    
    # Create DI container
    container = create_container()
    
    # Get services from container
    queue = RedisQueue()
    processor = EventProcessor(
        validator=container.get(EventValidatorProtocol),
        task_service=container.get(TaskServiceProtocol),
        card_service=container.get(CardServiceProtocol),
        dedup_service=container.get(DeduplicationServiceProtocol),
        settings=get_settings(),
    )
    
    logger.info("Worker started with dependency injection")
    # ... rest of implementation
```

## Implementation Instructions

1. **Create Service Interfaces**: Define Protocol interfaces for all external dependencies
2. **Extract Single-Purpose Classes**: Break down EventProcessor into focused service classes
3. **Implement DI Container**: Create simple dependency injection container
4. **Update Constructors**: Modify all classes to accept dependencies via constructor injection
5. **Create Factory Functions**: Implement factory functions for complex object creation
6. **Update Tests**: Modify tests to use mock implementations of protocols

## Success Criteria
- [ ] EventProcessor has single responsibility (orchestration only)
- [ ] All external dependencies injected via constructor
- [ ] Service classes follow single responsibility principle
- [ ] Protocol interfaces defined for all external services
- [ ] DI container manages object lifecycle
- [ ] Code is easily testable with mock implementations
- [ ] New features can be added without modifying existing code

## Related Files
- `app/worker/asana_client.py` - Implement AsanaClientProtocol
- `app/worker/trello_client.py` - Implement TrelloClientProtocol
- `app/worker/deduplication.py` - Implement DeduplicationServiceProtocol
- `tests/` - Create comprehensive test suite using mocks

## Rationale
SOLID principles provide:
- **Maintainability**: Easier to understand and modify individual components
- **Testability**: Each component can be tested in isolation
- **Extensibility**: New features can be added without changing existing code
- **Flexibility**: Dependencies can be swapped without affecting consumers
- **Reusability**: Components can be reused in different contexts

This architectural refactoring is essential for long-term maintainability and enables proper testing practices.