"""Package de gestion des événements."""
import importlib
import pkgutil
from typing import Dict, Callable, Any

from azure.eventhub.aio import PartitionContext
from azure.eventhub import EventData

# Registry des handlers d'événements
event_handlers: Dict[str, Dict[str, Callable]] = {}


def register_event_handler(event_name: str, handler_type: str, handler: Callable):
    """Enregistre un handler d'événement."""
    if event_name not in event_handlers:
        event_handlers[event_name] = {}
    event_handlers[event_name][handler_type] = handler


def get_event_handler(event_name: str, handler_type: str) -> Callable:
    """Récupère un handler d'événement."""
    return event_handlers.get(event_name, {}).get(handler_type)


# Import automatique de tous les handlers d'événements
import app.events.  # noqa: F401

