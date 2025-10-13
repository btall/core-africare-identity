"""Classe de base pour les handlers d'événements Redis."""

import logging
from abc import ABC, abstractmethod
from typing import Any


class BaseEventHandler(ABC):
    """Classe de base pour tous les handlers d'événements Redis."""

    def __init__(self, event_name: str):
        self.event_name = event_name
        self.logger = logging.getLogger(f"{__name__}.{event_name}")

    @abstractmethod
    async def handle_event(self, payload: dict[str, Any]):
        """Traite un événement reçu depuis Redis Pub/Sub.

        Args:
            payload: Dictionnaire contenant les données de l'événement
        """
        pass

    async def handle_error(self, error: Exception):
        """Gère les erreurs lors de la réception des événements.

        Args:
            error: L'exception levée pendant le traitement
        """
        self.logger.error(
            f"Erreur lors de la réception des événements pour {self.event_name}: {error}",
            exc_info=True,
        )

    async def on_event(self, payload: dict[str, Any]):
        """Point d'entrée pour les événements - avec logging et gestion d'erreur.

        Args:
            payload: Dictionnaire contenant les données de l'événement
        """
        try:
            self.logger.debug(f"Événement reçu sur {self.event_name}: {payload}")
            await self.handle_event(payload)
        except Exception as e:
            await self.handle_error(e)

    async def on_error(self, error: Exception):
        """Point d'entrée pour les erreurs.

        Args:
            error: L'exception à gérer
        """
        await self.handle_error(error)
