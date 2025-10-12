"""Tests unitaires pour le service de synchronisation Keycloak."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient
from app.schemas.keycloak import KeycloakEventDetails, KeycloakWebhookEvent
from app.services.keycloak_sync_service import (
    _create_patient_from_event,
    sync_email_update,
    sync_profile_update,
    sync_user_registration,
    track_user_login,
)


@pytest.fixture
def mock_db_session():
    """Fixture pour une session de base de données mockée."""
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def sample_register_event():
    """Fixture pour un événement REGISTER valide."""
    import time as time_module

    return KeycloakWebhookEvent(
        type="REGISTER",
        realmId="africare",
        clientId="core-africare-identity",
        userId="test-user-123",
        ipAddress="192.168.1.1",
        sessionId="session-uuid",
        details=KeycloakEventDetails(
            username="amadou.diallo",
            email="amadou.diallo@example.sn",
            first_name="Amadou",
            last_name="Diallo",
            date_of_birth="1990-05-15",
            gender="male",
            phone="+221771234567",
            country="Sénégal",
            preferred_language="fr",
        ),
        time=int(time_module.time() * 1000),  # Timestamp actuel en millisecondes
    )


@pytest.fixture
def sample_update_profile_event():
    """Fixture pour un événement UPDATE_PROFILE valide."""
    import time as time_module

    return KeycloakWebhookEvent(
        type="UPDATE_PROFILE",
        realmId="africare",
        clientId="core-africare-identity",
        userId="test-user-123",
        ipAddress="192.168.1.1",
        sessionId="session-uuid",
        details=KeycloakEventDetails(
            first_name="Amadou Updated",
            last_name="Diallo Updated",
            phone="+221771234999",
        ),
        time=int(time_module.time() * 1000),
    )


@pytest.fixture
def sample_update_email_event():
    """Fixture pour un événement UPDATE_EMAIL valide."""
    import time as time_module

    return KeycloakWebhookEvent(
        type="UPDATE_EMAIL",
        realmId="africare",
        clientId="core-africare-identity",
        userId="test-user-123",
        ipAddress="192.168.1.1",
        sessionId="session-uuid",
        details=KeycloakEventDetails(
            email="new.email@example.sn",
            email_verified=True,
        ),
        time=int(time_module.time() * 1000),
    )


@pytest.fixture
def sample_login_event():
    """Fixture pour un événement LOGIN valide."""
    import time as time_module

    return KeycloakWebhookEvent(
        type="LOGIN",
        realmId="africare",
        clientId="core-africare-identity",
        userId="test-user-123",
        ipAddress="192.168.1.1",
        sessionId="session-uuid",
        details=KeycloakEventDetails(),
        time=int(time_module.time() * 1000),
    )


class TestCreatePatientFromEvent:
    """Tests pour la création d'un patient depuis un événement."""

    @pytest.mark.asyncio
    async def test_create_patient_valid_data(self, mock_db_session, sample_register_event):
        """Test création patient avec données valides."""
        patient = await _create_patient_from_event(mock_db_session, sample_register_event)

        assert patient.keycloak_user_id == "test-user-123"
        assert patient.first_name == "Amadou"
        assert patient.last_name == "Diallo"
        assert patient.date_of_birth == date(1990, 5, 15)
        assert patient.gender == "male"
        assert patient.email == "amadou.diallo@example.sn"
        assert patient.phone == "+221771234567"
        assert patient.country == "Sénégal"
        assert patient.preferred_language == "fr"
        assert patient.is_active is True

        mock_db_session.add.assert_called_once_with(patient)

    @pytest.mark.asyncio
    async def test_create_patient_missing_first_name(self, mock_db_session):
        """Test création patient sans prénom (erreur)."""
        event = KeycloakWebhookEvent(
            type="REGISTER",
            realmId="africare",
            userId="test-user",
            details=KeycloakEventDetails(
                last_name="Diallo",
                date_of_birth="1990-05-15",
                gender="male",
            ),
            time=int(__import__("time").time() * 1000),
        )

        with pytest.raises(ValueError, match="first_name et last_name sont requis"):
            await _create_patient_from_event(mock_db_session, event)

    @pytest.mark.asyncio
    async def test_create_patient_missing_date_of_birth(self, mock_db_session):
        """Test création patient sans date de naissance (erreur)."""
        event = KeycloakWebhookEvent(
            type="REGISTER",
            realmId="africare",
            userId="test-user",
            details=KeycloakEventDetails(
                first_name="Amadou",
                last_name="Diallo",
                gender="male",
            ),
            time=int(__import__("time").time() * 1000),
        )

        with pytest.raises(ValueError, match="date_of_birth est requis"):
            await _create_patient_from_event(mock_db_session, event)

    @pytest.mark.asyncio
    async def test_create_patient_invalid_date_format(self, mock_db_session):
        """Test création patient avec format de date invalide."""
        event = KeycloakWebhookEvent(
            type="REGISTER",
            realmId="africare",
            userId="test-user",
            details=KeycloakEventDetails(
                first_name="Amadou",
                last_name="Diallo",
                date_of_birth="15/05/1990",  # Format invalide
                gender="male",
            ),
            time=int(__import__("time").time() * 1000),
        )

        with pytest.raises(ValueError, match="Format date_of_birth invalide"):
            await _create_patient_from_event(mock_db_session, event)

    @pytest.mark.asyncio
    async def test_create_patient_missing_gender(self, mock_db_session):
        """Test création patient sans genre (erreur)."""
        event = KeycloakWebhookEvent(
            type="REGISTER",
            realmId="africare",
            userId="test-user",
            details=KeycloakEventDetails(
                first_name="Amadou",
                last_name="Diallo",
                date_of_birth="1990-05-15",
            ),
            time=int(__import__("time").time() * 1000),
        )

        with pytest.raises(ValueError, match="gender est requis"):
            await _create_patient_from_event(mock_db_session, event)


class TestSyncUserRegistration:
    """Tests pour la synchronisation REGISTER."""

    @pytest.mark.asyncio
    async def test_sync_registration_new_user(self, mock_db_session, sample_register_event):
        """Test création d'un nouveau patient lors de REGISTER."""
        # Mock: pas de patient existant
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.keycloak_sync_service.publish", new_callable=AsyncMock
        ) as mock_publish:
            result = await sync_user_registration(mock_db_session, sample_register_event)

        assert result.success is True
        assert result.event_type == "REGISTER"
        assert result.user_id == "test-user-123"
        assert result.patient_id is not None
        assert "Patient created" in result.message

        mock_db_session.commit.assert_called_once()
        mock_publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_registration_existing_user(self, mock_db_session, sample_register_event):
        """Test REGISTER pour un utilisateur déjà existant (idempotence)."""
        # Mock: patient existant
        existing_patient = Patient(
            id=42,
            keycloak_user_id="test-user-123",
            first_name="Amadou",
            last_name="Diallo",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_patient
        mock_db_session.execute.return_value = mock_result

        result = await sync_user_registration(mock_db_session, sample_register_event)

        assert result.success is True
        assert result.event_type == "REGISTER"
        assert result.user_id == "test-user-123"
        assert result.patient_id is None
        assert "already synchronized" in result.message

        # Ne doit pas créer de nouveau patient
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_registration_publishes_event(self, mock_db_session, sample_register_event):
        """Test que REGISTER publie un événement identity.patient.created."""
        # Mock: pas de patient existant
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.keycloak_sync_service.publish", new_callable=AsyncMock
        ) as mock_publish:
            await sync_user_registration(mock_db_session, sample_register_event)

        # Vérifier que l'événement a été publié
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][0] == "identity.patient.created"
        payload = call_args[0][1]
        assert "patient_id" in payload
        assert payload["keycloak_user_id"] == "test-user-123"


class TestSyncProfileUpdate:
    """Tests pour la synchronisation UPDATE_PROFILE."""

    @pytest.mark.asyncio
    async def test_sync_profile_update_existing_patient(
        self, mock_db_session, sample_update_profile_event
    ):
        """Test mise à jour du profil d'un patient existant."""
        # Mock: patient existant
        existing_patient = Patient(
            id=42,
            keycloak_user_id="test-user-123",
            first_name="Amadou",
            last_name="Diallo",
            phone="+221771234567",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_patient
        mock_db_session.execute.return_value = mock_result

        with patch("app.services.keycloak_sync_service.publish", new_callable=AsyncMock):
            result = await sync_profile_update(mock_db_session, sample_update_profile_event)

        assert result.success is True
        assert result.patient_id == 42
        assert existing_patient.first_name == "Amadou Updated"
        assert existing_patient.last_name == "Diallo Updated"
        assert existing_patient.phone == "+221771234999"

        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_profile_update_patient_not_found(
        self, mock_db_session, sample_update_profile_event
    ):
        """Test UPDATE_PROFILE pour un patient inexistant."""
        # Mock: pas de patient trouvé
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await sync_profile_update(mock_db_session, sample_update_profile_event)

        assert result.success is False
        assert "Patient not found" in result.message
        mock_db_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_profile_update_no_changes(self, mock_db_session):
        """Test UPDATE_PROFILE sans changements."""
        event = KeycloakWebhookEvent(
            type="UPDATE_PROFILE",
            realmId="africare",
            userId="test-user-123",
            details=KeycloakEventDetails(),  # Pas de champs à mettre à jour
            time=int(__import__("time").time() * 1000),
        )

        existing_patient = Patient(
            id=42,
            keycloak_user_id="test-user-123",
            first_name="Amadou",
            last_name="Diallo",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_patient
        mock_db_session.execute.return_value = mock_result

        with patch("app.services.keycloak_sync_service.publish", new_callable=AsyncMock):
            result = await sync_profile_update(mock_db_session, event)

        assert result.success is True
        assert "No changes" in result.message
        # Commit ne devrait pas être appelé (pas de modifications)


class TestSyncEmailUpdate:
    """Tests pour la synchronisation UPDATE_EMAIL."""

    @pytest.mark.asyncio
    async def test_sync_email_update_existing_patient(
        self, mock_db_session, sample_update_email_event
    ):
        """Test mise à jour de l'email d'un patient existant."""
        # Mock: patient existant
        existing_patient = Patient(
            id=42,
            keycloak_user_id="test-user-123",
            email="old.email@example.sn",
            is_verified=False,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_patient
        mock_db_session.execute.return_value = mock_result

        with patch(
            "app.services.keycloak_sync_service.publish", new_callable=AsyncMock
        ) as mock_publish:
            result = await sync_email_update(mock_db_session, sample_update_email_event)

        assert result.success is True
        assert result.patient_id == 42
        assert existing_patient.email == "new.email@example.sn"
        assert existing_patient.is_verified is True

        mock_db_session.commit.assert_called_once()
        mock_publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_email_update_patient_not_found(
        self, mock_db_session, sample_update_email_event
    ):
        """Test UPDATE_EMAIL pour un patient inexistant."""
        # Mock: pas de patient trouvé
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        result = await sync_email_update(mock_db_session, sample_update_email_event)

        assert result.success is False
        assert "Patient not found" in result.message
        mock_db_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_email_update_missing_email(self, mock_db_session):
        """Test UPDATE_EMAIL sans email dans l'événement."""
        event = KeycloakWebhookEvent(
            type="UPDATE_EMAIL",
            realmId="africare",
            userId="test-user-123",
            details=KeycloakEventDetails(),  # Email manquant
            time=int(__import__("time").time() * 1000),
        )

        existing_patient = Patient(id=42, keycloak_user_id="test-user-123")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_patient
        mock_db_session.execute.return_value = mock_result

        result = await sync_email_update(mock_db_session, event)

        assert result.success is False
        assert "Email missing" in result.message
        mock_db_session.commit.assert_not_called()


class TestTrackUserLogin:
    """Tests pour le tracking LOGIN."""

    @pytest.mark.asyncio
    async def test_track_login_publishes_event(self, mock_db_session, sample_login_event):
        """Test que LOGIN publie un événement identity.user.login."""
        with patch(
            "app.services.keycloak_sync_service.publish", new_callable=AsyncMock
        ) as mock_publish:
            result = await track_user_login(mock_db_session, sample_login_event)

        assert result.success is True
        assert result.event_type == "LOGIN"
        assert "Login tracked" in result.message

        # Vérifier l'événement publié
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        assert call_args[0][0] == "identity.user.login"
        payload = call_args[0][1]
        assert payload["keycloak_user_id"] == "test-user-123"
        assert payload["ip_address"] == "192.168.1.1"
        assert payload["session_id"] == "session-uuid"

    @pytest.mark.asyncio
    async def test_track_login_does_not_modify_database(self, mock_db_session, sample_login_event):
        """Test que LOGIN ne modifie pas la base de données."""
        with patch("app.services.keycloak_sync_service.publish", new_callable=AsyncMock):
            await track_user_login(mock_db_session, sample_login_event)

        # Aucune modification DB
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_not_called()
        mock_db_session.execute.assert_not_called()
