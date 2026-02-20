"""Dependency injection container."""

from typing import Dict, Any, Callable, TypeVar, Type
from dataclasses import dataclass

from app.config import get_settings
from app.worker.asana_client import AsanaClient
from app.worker.trello_client import TrelloClient
from app.worker.deduplication import Deduplication
from app.worker.attachments import AttachmentProcessor
from app.services.protocols import (
    EventValidatorProtocol,
    TaskServiceProtocol,
    CardServiceProtocol,
    DeduplicationServiceProtocol,
    AsanaClientProtocol,
    TrelloClientProtocol,
)
from app.services.event_validator import EventValidator
from app.services.task_service import TaskService
from app.services.card_service import CardService
from app.services.deduplication_service import DeduplicationService

T = TypeVar('T')


@dataclass
class ServiceDefinition:
    """Service definition for DI container."""
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


def create_container() -> DIContainer:
    """Create and configure the DI container."""
    container = DIContainer()
    
    # Register concrete implementations
    container.register(AsanaClientProtocol, lambda: AsanaClient())
    container.register(TrelloClientProtocol, lambda: TrelloClient())
    
    # Register services with dependencies
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
    container.register(
        DeduplicationServiceProtocol, 
        lambda: DeduplicationService(Deduplication())
    )
    
    return container