"""
Interface abstraite pour les systèmes de messaging événementiels.

Ce module définit le contrat que tout backend de messaging (Redis, Event Hub, etc.)
doit implémenter pour assurer l'interchangeabilité.

Pattern: Strategy/Interface Segregation Principle
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


class EventBusInterface(ABC):
    """
    Interface abstraite pour un système de messaging événementiel.

    Tout backend (Redis, Azure Event Hub, RabbitMQ, Kafka, etc.) doit implémenter
    cette interface pour garantir l'interchangeabilité sans modifier le code client.

    Exemple d'implémentation:
        class RedisEventBus(EventBusInterface):
            async def publish(self, subject: str, payload: dict | BaseModel, max_retries: int = 3):
                # Implémentation Redis Pub/Sub
                ...

            def subscribe(self, subject: str):
                # Décorateur pour handlers Redis
                ...

            async def lifespan(self, app: FastAPI):
                # Cycle de vie Redis
                ...
    """

    @abstractmethod
    async def publish(
        self,
        subject: str,
        payload: dict | BaseModel,
        max_retries: int = 3
    ) -> None:
        """
        Publie un événement.

        Args:
            subject: Sujet de l'événement (ex: "user.created")
            payload: Données de l'événement (dict ou modèle Pydantic)
            max_retries: Nombre maximum de tentatives

        Raises:
            Exception: Si toutes les tentatives échouent

        Example:
            await event_bus.publish("user.created", {"user_id": "123"})
        """
        pass

    @abstractmethod
    def subscribe(self, subject: str) -> Callable:
        """
        Décorateur pour enregistrer un handler d'événement.

        Args:
            subject: Sujet de l'événement à écouter

        Returns:
            Callable: Décorateur pour la fonction handler

        Example:
            @event_bus.subscribe("user.created")
            async def handle_user_created(payload: dict):
                print(f"User created: {payload}")
        """
        pass

    @abstractmethod
    async def lifespan(self, app: FastAPI) -> Any:
        """
        Gestionnaire de cycle de vie pour FastAPI.

        Initialise les clients, démarre les consumers, et assure un shutdown graceful.

        Args:
            app: Instance FastAPI

        Yields:
            None: Pendant que l'application est active

        Example:
            @asynccontextmanager
            async def lifespan(app: FastAPI):
                # Startup
                await init_messaging()
                yield
                # Shutdown
                await close_messaging()
        """
        pass

    @abstractmethod
    async def get_publisher(self) -> Callable:
        """
        Retourne la fonction publish pour injection de dépendance FastAPI.

        Returns:
            Callable: Fonction publish

        Example:
            async def my_endpoint(
                publisher: Callable = Depends(event_bus.get_publisher)
            ):
                await publisher("event.subject", {"data": "value"})
        """
        pass


# Type alias pour les handlers d'événements
EventHandler = Callable[[dict], Awaitable[None]]


__all__ = [
    "EventBusInterface",
    "EventHandler",
]
