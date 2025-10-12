"""Package de gestion des événements."""

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any

from azure.eventhub import EventData
from azure.eventhub.aio import PartitionContext

# Registry des handlers d'événements
event_handlers: dict[str, dict[str, Callable]] = {}


def register_event_handler(event_name: str, handler_type: str, handler: Callable):
    """Enregistre un handler d'événement."""
    if event_name not in event_handlers:
        event_handlers[event_name] = {}
    event_handlers[event_name][handler_type] = handler


def get_event_handler(event_name: str, handler_type: str) -> Callable:
    """Récupère un handler d'événement."""
    return event_handlers.get(event_name, {}).get(handler_type)
