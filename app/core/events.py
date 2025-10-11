"""
Event System Facade - core-africare-identity

Ce module sert de façade unifiée pour le système d'événements.
Il importe automatiquement le bon backend (Redis ou Event Hub) selon la
configuration du cookiecutter, garantissant ainsi une API cohérente
indépendamment du backend utilisé.

Backend configuré : redis

Usage:
    from app.core.events import publish, subscribe, lifespan

    # Publication d'événement
    await publish("user.created", {"user_id": "123"})

    # Consommation d'événement
    @subscribe("user.created")
    async def handle_user_created(payload: dict):
        print(f"User created: {payload}")

    # Lifespan FastAPI
    app = FastAPI(lifespan=lifespan)

Note:
    Ce fichier est généré automatiquement par cookiecutter.
    L'implémentation réelle se trouve dans:
    - app/core/events_redis.py (Redis Pub/Sub)
    """

# Import du backend Redis Pub/Sub (Phase 1 MVP)
from app.core.events_redis import (
    get_publisher,
    lifespan,
    publish,
    subscribe,
)

# Information pour le debugging
_BACKEND = "redis"
_BACKEND_VERSION = "Redis Pub/Sub (Phase 1 MVP)"

__all__ = [
    "publish",
    "subscribe",
    "get_publisher",
    "lifespan",
]


# Fonction utilitaire pour debugging
def get_backend_info() -> dict:
    """
    Retourne les informations sur le backend messaging actif.

    Returns:
        dict: Informations sur le backend
            {
                "backend": "redis" | "eventhub",
                "version": "Description du backend",
                "module": "app.core.events_redis" | "app.core.events_eventhub"
            }

    Example:
        >>> from app.core.events import get_backend_info
        >>> info = get_backend_info()
        >>> print(f"Backend actif: {info['backend']}")
        Backend actif: redis
    """
    return {
        "backend": _BACKEND,
        "version": _BACKEND_VERSION,
        "module": "app.core.events_redis",
        }
