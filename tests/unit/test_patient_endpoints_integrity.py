"""Tests unitaires pour la gestion des IntegrityError dans les endpoints patients."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.v1.endpoints.patients import create_patient
from app.schemas.patient import PatientCreate


class TestPatientIntegrityErrors:
    """Tests pour la gestion des IntegrityError (problème #8 IMPORTANT)."""

    @pytest.mark.asyncio
    async def test_create_patient_duplicate_email_returns_409(self):
        """Test qu'un email dupliqué retourne 409 Conflict."""
        patient_data = PatientCreate(
            keycloak_user_id="user-123",
            first_name="Amadou",
            last_name="Diallo",
            email="amadou.diallo@example.sn",
            phone="+221771234567",
            date_of_birth="1990-01-01",
            gender="male",
            country="Sénégal",
            preferred_language="fr",
        )

        db = AsyncMock()
        current_user = {"sub": "admin-123"}

        # Simuler une IntegrityError pour email dupliqué
        with patch("app.services.patient_service.create_patient") as mock_create:
            mock_create.side_effect = IntegrityError(
                "INSERT INTO patients",
                {},
                Exception("UNIQUE constraint failed: patients.email"),
            )

            with pytest.raises(HTTPException) as exc_info:
                await create_patient(patient_data, db, current_user)

            # Doit retourner 409 Conflict (pas 500)
            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "email" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_create_patient_duplicate_keycloak_id_returns_409(self):
        """Test qu'un keycloak_user_id dupliqué retourne 409 Conflict."""
        patient_data = PatientCreate(
            keycloak_user_id="user-123",
            first_name="Fatou",
            last_name="Sow",
            email="fatou.sow@example.sn",
            phone="+221771111111",
            date_of_birth="1992-05-15",
            gender="female",
            country="Sénégal",
            preferred_language="fr",
        )

        db = AsyncMock()
        current_user = {"sub": "admin-456"}

        with patch("app.services.patient_service.create_patient") as mock_create:
            mock_create.side_effect = IntegrityError(
                "INSERT INTO patients",
                {},
                Exception("UNIQUE constraint failed: patients.keycloak_user_id"),
            )

            with pytest.raises(HTTPException) as exc_info:
                await create_patient(patient_data, db, current_user)

            # Doit retourner 409 Conflict avec message keycloak_user_id
            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "keycloak_user_id" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_create_patient_duplicate_national_id_returns_409(self):
        """Test qu'un national_id dupliqué retourne 409 Conflict."""
        patient_data = PatientCreate(
            keycloak_user_id="user-789",
            first_name="Mamadou",
            last_name="Ba",
            email="mamadou.ba@example.sn",
            phone="+221772222222",
            date_of_birth="1988-03-20",
            gender="male",
            country="Sénégal",
            preferred_language="fr",
            national_id="1234567890123",
        )

        db = AsyncMock()
        current_user = {"sub": "admin-789"}

        with patch("app.services.patient_service.create_patient") as mock_create:
            mock_create.side_effect = IntegrityError(
                "INSERT INTO patients",
                {},
                Exception("UNIQUE constraint failed: patients.national_id"),
            )

            with pytest.raises(HTTPException) as exc_info:
                await create_patient(patient_data, db, current_user)

            # Doit retourner 409 Conflict avec message national_id
            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert (
                "national_id" in exc_info.value.detail.lower()
                or "identifiant national" in exc_info.value.detail.lower()
            )

    @pytest.mark.asyncio
    async def test_create_patient_success_returns_201(self):
        """Test qu'un patient valide est créé avec succès."""
        from datetime import date, datetime

        from app.models.patient import Patient

        patient_data = PatientCreate(
            keycloak_user_id="user-new",
            first_name="Ndeye",
            last_name="Diop",
            email="ndeye.diop@example.sn",
            phone="+221773333333",
            date_of_birth="1995-07-10",
            gender="female",
            country="Sénégal",
            preferred_language="fr",
        )

        db = AsyncMock()
        current_user = {"sub": "admin-999"}

        # Créer un objet Patient réel (pas un mock)
        mock_patient = Patient(
            id=123,
            keycloak_user_id="user-new",
            first_name="Ndeye",
            last_name="Diop",
            email="ndeye.diop@example.sn",
            phone="+221773333333",
            date_of_birth=date(1995, 7, 10),
            gender="female",
            country="Sénégal",
            preferred_language="fr",
            is_active=True,
            is_verified=False,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        with patch("app.services.patient_service.create_patient") as mock_create:
            mock_create.return_value = mock_patient

            result = await create_patient(patient_data, db, current_user)

            # Doit retourner le patient créé
            assert result.id == 123
            assert result.email == "ndeye.diop@example.sn"
