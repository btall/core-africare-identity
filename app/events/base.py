"""Classe de base pour les handlers d'événements."""

import logging
from abc import ABC, abstractmethod

from azure.eventhub import EventData
from azure.eventhub.aio import PartitionContext


class BaseEventHandler(ABC):
    """Classe de base pour tous les handlers d'événements."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        self.logger = logging.getLogger(f"{__name__}.{event_name}")

    @abstractmethod
    async def handle_event(self, partition_context: PartitionContext, event: EventData):
        """Traite un événement reçu."""
        pass

    async def handle_error(self, partition_context: PartitionContext, error: Exception):
        """Gère les erreurs lors de la réception des événements."""
        self.logger.error(
            f"Erreur lors de la réception des événements pour {self.event_name}: {error}"
        )
        await partition_context.update_checkpoint(None)

    async def on_event(self, partition_context: PartitionContext, event: EventData):
        """Point d'entrée pour les événements - avec logging et checkpoint."""
        try:
            self.logger.debug(f"Événement reçu sur {self.event_name}: {event}")
            await self.handle_event(partition_context, event)
            await partition_context.update_checkpoint(event)
        except Exception as e:
            await self.handle_error(partition_context, e)

    async def on_error(self, partition_context: PartitionContext, error: Exception):
        """Point d'entrée pour les erreurs."""
        await self.handle_error(partition_context, error)
