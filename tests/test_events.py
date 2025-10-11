"""
Tests unitaires pour le système d'événements.

Tests génériques compatibles avec tous les backends (Redis, Event Hub)
grâce au pattern Interface.

Backend testé : redis
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.events import get_publisher, lifespan, publish, subscribe


class TestEventModel(BaseModel):
    """Modèle Pydantic pour tester la publication avec modèles."""

    test_id: str
    test_data: str


@pytest.mark.asyncio
class TestEventsPublish:
    """Tests de publication d'événements."""

    @patch("app.core.events_redis.redis_client")
    async def test_publish_dict_payload(self, mock_redis):
        """Test publication avec payload dict."""
        # Setup
        mock_redis.publish = AsyncMock()

        # Action
        await publish("test.event", {"test_id": "123", "data": "test"})

        # Assertions
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "test.event"  # Subject
        # Payload est JSON avec métadonnées
        import json
        event_data = json.loads(call_args[0][1])
        assert event_data["subject"] == "test.event"
        assert event_data["data"]["test_id"] == "123"
        assert "id" in event_data  # Message ID
        assert "timestamp" in event_data

    @patch("app.core.events_redis.redis_client")
    async def test_publish_pydantic_model(self, mock_redis):
        """Test publication avec modèle Pydantic."""
        # Setup
        mock_redis.publish = AsyncMock()
        event = TestEventModel(test_id="123", test_data="test")

        # Action
        await publish("test.event", event)

        # Assertions
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        import json
        event_data = json.loads(call_args[0][1])
        assert event_data["data"]["test_id"] == "123"
        assert event_data["data"]["test_data"] == "test"

    @patch("app.core.events_redis.redis_client")
    async def test_publish_retry_on_failure(self, mock_redis):
        """Test retry automatique en cas d'échec."""
        # Setup - échoue 2 fois puis réussit
        mock_redis.publish = AsyncMock(
            side_effect=[
                Exception("Connection error"),
                Exception("Connection error"),
                None  # Succès au 3ème essai
            ]
        )

        # Action - ne doit pas lever d'exception (retry réussit)
        await publish("test.event", {"test": "data"}, max_retries=3)

        # Assertions
        assert mock_redis.publish.call_count == 3

    @patch("app.core.events_redis.redis_client")
    async def test_publish_max_retries_exceeded(self, mock_redis):
        """Test échec après épuisement des retries."""
        # Setup - toujours en échec
        mock_redis.publish = AsyncMock(side_effect=Exception("Connection error"))

        # Action & Assertions
        with pytest.raises(Exception, match="Connection error"):
            await publish("test.event", {"test": "data"}, max_retries=2)

        assert mock_redis.publish.call_count == 2

    @pytest.mark.asyncio
class TestEventsSubscribe:
    """Tests de souscription aux événements."""

    def test_subscribe_decorator(self):
        """Test enregistrement d'un handler via @subscribe."""
        # Setup
        handler_called = False
        handler_payload = None

        @subscribe("test.event")
        async def test_handler(payload: dict):
            nonlocal handler_called, handler_payload
            handler_called = True
            handler_payload = payload

        # Assertions
        from app.core.events_redis import handlers
        assert "test.event" in handlers
        assert test_handler in handlers["test.event"]

    @pytest.mark.asyncio
    async def test_handler_execution(self):
        """Test exécution d'un handler enregistré."""
        # Setup
        received_payloads = []

        @subscribe("test.handler.execution")
        async def test_handler(payload: dict):
            received_payloads.append(payload)

        # Simuler l'appel du handler
        test_payload = {"test_id": "123", "data": "test"}
        await test_handler(test_payload)

        # Assertions
        assert len(received_payloads) == 1
        assert received_payloads[0]["test_id"] == "123"


@pytest.mark.asyncio
class TestEventsLifespan:
    """Tests du cycle de vie FastAPI."""

    @patch("app.core.events_redis.init_redis")
    @patch("app.core.events_redis.start_consuming")
    @patch("app.core.events_redis.stop_consuming")
    @patch("app.core.events_redis.close_redis")
    async def test_lifespan_startup_shutdown(
        self,
        mock_close,
        mock_stop,
        mock_start,
        mock_init
    ):
        """Test startup et shutdown du lifespan."""
        # Setup
        mock_init.return_value = AsyncMock()
        mock_start.return_value = AsyncMock()
        mock_stop.return_value = AsyncMock()
        mock_close.return_value = AsyncMock()

        app = FastAPI()

        # Action - simuler lifespan
        async with lifespan(app):
            # Vérifier startup
            mock_init.assert_called_once()
            mock_start.assert_called_once()

        # Vérifier shutdown
        mock_stop.assert_called_once()
        mock_close.assert_called_once()

    @pytest.mark.asyncio
class TestEventsDependencyInjection:
    """Tests de l'injection de dépendance FastAPI."""

    async def test_get_publisher(self):
        """Test récupération de la fonction publish via get_publisher."""
        publisher = await get_publisher()

        # Assertions
        assert callable(publisher)
        assert publisher == publish


@pytest.mark.asyncio
class TestEventsIntegration:
    """Tests d'intégration bout-en-bout."""

    @pytest.mark.skipif(
        "redis" == "eventhub",
        reason="Nécessite Azure Event Hub réel"
    )
    @patch("app.core.events_redis.redis_client")
    async def test_publish_subscribe_integration(self, mock_redis):
        """Test intégration publish/subscribe (Redis)."""
        # Setup
        mock_redis.publish = AsyncMock()
        received_events = []

        @subscribe("integration.test")
        async def integration_handler(payload: dict):
            received_events.append(payload)

        # Action
        test_payload = {"integration": "test", "data": "value"}
        await publish("integration.test", test_payload)

        # Assertions
        mock_redis.publish.assert_called_once()
        # Handler sera appelé par le consumer Redis (hors scope de ce test)

    def test_backend_info():
    """Test fonction utilitaire get_backend_info."""
    from app.core.events import get_backend_info

    info = get_backend_info()

    # Assertions
    assert "backend" in info
    assert "version" in info
    assert "module" in info
    assert info["backend"] == "redis"
