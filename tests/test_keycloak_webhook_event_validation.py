"""Tests unitaires pour la validation des timestamps des webhooks Keycloak.

Ce module teste la validation temporelle (30 jours) des événements webhook,
garantissant que les replays et les événements en backlog sont acceptés.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.keycloak import KeycloakWebhookEvent


class TestKeycloakWebhookEventTimestampValidation:
    """Tests de validation du timestamp des événements webhook."""

    def test_event_time_recent_accepted(self):
        """Les événements récents (dernière heure) sont acceptés."""
        now_ms = int(datetime.now().timestamp() * 1000)
        event_data = {
            "eventType": "REGISTER",
            "realmId": "africare",
            "userId": "test-user-123",
            "eventTime": now_ms - (30 * 60 * 1000),  # 30 minutes ago
        }

        event = KeycloakWebhookEvent.model_validate(event_data)
        assert event.event_time == now_ms - (30 * 60 * 1000)

    def test_event_time_yesterday_accepted(self):
        """Les événements d'hier (24h) sont acceptés."""
        now_ms = int(datetime.now().timestamp() * 1000)
        yesterday_ms = now_ms - (24 * 60 * 60 * 1000)  # 24 hours ago

        event_data = {
            "eventType": "UPDATE_PROFILE",
            "realmId": "africare",
            "userId": "test-user-456",
            "eventTime": yesterday_ms,
        }

        event = KeycloakWebhookEvent.model_validate(event_data)
        assert event.event_time == yesterday_ms

    def test_event_time_three_days_ago_accepted(self):
        """Les événements de 3 jours (comme dans l'erreur originale) sont acceptés."""
        now_ms = int(datetime.now().timestamp() * 1000)
        three_days_ago_ms = now_ms - (3 * 24 * 60 * 60 * 1000)  # 3 days ago

        event_data = {
            "eventType": "LOGIN",
            "realmId": "africare",
            "userId": "test-user-789",
            "eventTime": three_days_ago_ms,
        }

        event = KeycloakWebhookEvent.model_validate(event_data)
        assert event.event_time == three_days_ago_ms

    def test_event_time_seven_days_ago_accepted(self):
        """Les événements de 7 jours sont acceptés."""
        now_ms = int(datetime.now().timestamp() * 1000)
        seven_days_ago_ms = now_ms - (7 * 24 * 60 * 60 * 1000)  # 7 days ago

        event_data = {
            "eventType": "UPDATE_EMAIL",
            "realmId": "africare",
            "userId": "test-user-101",
            "eventTime": seven_days_ago_ms,
        }

        event = KeycloakWebhookEvent.model_validate(event_data)
        assert event.event_time == seven_days_ago_ms

    def test_event_time_thirty_days_ago_accepted(self):
        """Les événements de 30 jours (limite maximum) sont acceptés."""
        now_ms = int(datetime.now().timestamp() * 1000)
        thirty_days_ago_ms = now_ms - (30 * 24 * 60 * 60 * 1000)  # 30 days ago

        event_data = {
            "eventType": "REGISTER",
            "realmId": "africare",
            "userId": "test-user-202",
            "eventTime": thirty_days_ago_ms + 1000,  # Légèrement moins de 30 jours
        }

        event = KeycloakWebhookEvent.model_validate(event_data)
        assert event.event_time == thirty_days_ago_ms + 1000

    def test_event_time_over_thirty_days_rejected(self):
        """Les événements de plus de 30 jours sont rejetés."""
        now_ms = int(datetime.now().timestamp() * 1000)
        over_thirty_days_ms = now_ms - (31 * 24 * 60 * 60 * 1000)  # 31 days ago

        event_data = {
            "eventType": "LOGIN",
            "realmId": "africare",
            "userId": "test-user-303",
            "eventTime": over_thirty_days_ms,
        }

        with pytest.raises(ValidationError) as exc_info:
            KeycloakWebhookEvent.model_validate(event_data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        # Pydantic utilise le nom du champ tel qu'il est dans l'input (camelCase)
        assert errors[0]["loc"] == ("eventTime",)
        assert "Timestamp invalide" in errors[0]["msg"]

    def test_event_time_near_future_accepted(self):
        """Les événements jusqu'à 1h dans le futur sont acceptés (décalage horaire)."""
        now_ms = int(datetime.now().timestamp() * 1000)
        near_future_ms = now_ms + (30 * 60 * 1000)  # 30 minutes in future

        event_data = {
            "eventType": "REGISTER",
            "realmId": "africare",
            "userId": "test-user-404",
            "eventTime": near_future_ms,
        }

        event = KeycloakWebhookEvent.model_validate(event_data)
        assert event.event_time == near_future_ms

    def test_event_time_far_future_rejected(self):
        """Les événements à plus de 1h dans le futur sont rejetés."""
        now_ms = int(datetime.now().timestamp() * 1000)
        far_future_ms = now_ms + (2 * 60 * 60 * 1000)  # 2 hours in future

        event_data = {
            "eventType": "LOGIN",
            "realmId": "africare",
            "userId": "test-user-505",
            "eventTime": far_future_ms,
        }

        with pytest.raises(ValidationError) as exc_info:
            KeycloakWebhookEvent.model_validate(event_data)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        # Pydantic utilise le nom du champ tel qu'il est dans l'input (camelCase)
        assert errors[0]["loc"] == ("eventTime",)
        assert "Timestamp invalide" in errors[0]["msg"]

    def test_timestamp_datetime_property(self):
        """La propriété timestamp_datetime convertit correctement le timestamp."""
        now = datetime.now()
        now_ms = int(now.timestamp() * 1000)

        event_data = {
            "eventType": "REGISTER",
            "realmId": "africare",
            "userId": "test-user-606",
            "eventTime": now_ms,
        }

        event = KeycloakWebhookEvent.model_validate(event_data)
        timestamp_dt = event.timestamp_datetime

        # Vérifier que la conversion est correcte (tolérance de 1 seconde)
        assert abs((timestamp_dt - now).total_seconds()) < 1

    def test_event_time_exact_boundary_thirty_days(self):
        """Test du cas limite exact: 30 jours exactement."""
        now_ms = int(datetime.now().timestamp() * 1000)
        exactly_thirty_days_ms = now_ms - (30 * 24 * 60 * 60 * 1000)

        event_data = {
            "eventType": "UPDATE_PROFILE",
            "realmId": "africare",
            "userId": "test-user-707",
            "eventTime": exactly_thirty_days_ms,
        }

        # 30 jours exactement devrait être accepté
        event = KeycloakWebhookEvent.model_validate(event_data)
        assert event.event_time == exactly_thirty_days_ms

    def test_event_time_exact_boundary_one_hour_future(self):
        """Test du cas limite exact: 1 heure dans le futur."""
        now_ms = int(datetime.now().timestamp() * 1000)
        exactly_one_hour_future_ms = now_ms + (60 * 60 * 1000)

        event_data = {
            "eventType": "REGISTER",
            "realmId": "africare",
            "userId": "test-user-808",
            "eventTime": exactly_one_hour_future_ms,
        }

        # 1 heure exactement devrait être accepté
        event = KeycloakWebhookEvent.model_validate(event_data)
        assert event.event_time == exactly_one_hour_future_ms

    def test_real_world_replay_scenario(self):
        """Test du scénario réel: replay d'événements après downtime de 4 jours."""
        # Simule l'erreur originale
        event_time_ms = 1761749965561  # Timestamp original de l'erreur
        now_ms = event_time_ms + (4 * 24 * 60 * 60 * 1000)  # 4 jours plus tard

        # Mock datetime.now() pour simuler le moment du traitement
        from unittest.mock import patch

        with patch("app.schemas.keycloak.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime.fromtimestamp(now_ms / 1000)

            event_data = {
                "eventType": "REGISTER",
                "realmId": "africare",
                "userId": "test-user-real",
                "eventTime": event_time_ms,
            }

            # Devrait maintenant être accepté avec la fenêtre de 30 jours
            event = KeycloakWebhookEvent.model_validate(event_data)
            assert event.event_time == event_time_ms
