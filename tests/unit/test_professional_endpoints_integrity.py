"""Tests unitaires pour la gestion des IntegrityError dans les endpoints professionnels."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.v1.endpoints.professionals import create_professional
from app.models.professional import Professional
from app.schemas.professional import ProfessionalCreate


class TestProfessionalIntegrityErrors:
    """Tests pour la gestion des IntegrityError (problème #8 IMPORTANT)."""

    @pytest.mark.asyncio
    async def test_create_professional_duplicate_email_returns_409(self):
        """Test qu'un email dupliqué retourne 409 Conflict."""
        professional_data = ProfessionalCreate(
            keycloak_user_id="user-123",
            first_name="Amadou",
            last_name="Diallo",
            email="dr.diallo@example.sn",
            phone="+221771234567",
            professional_type="physician",
            professional_id="SN-MD-12345",
            specialty="Médecine générale",
            facility_name="Hôpital Principal de Dakar",
            facility_city="Dakar",
            facility_region="Dakar",
            languages_spoken="fr,wo",
        )

        db = AsyncMock()
        current_user = {"sub": "admin-123"}

        # Simuler une IntegrityError pour email dupliqué
        with patch("app.services.professional_service.create_professional") as mock_create:
            mock_create.side_effect = IntegrityError(
                "INSERT INTO professionals",
                {},
                Exception("UNIQUE constraint failed: professionals.email"),
            )

            with pytest.raises(HTTPException) as exc_info:
                await create_professional(professional_data, db, current_user)

            # Doit retourner 409 Conflict (pas 400)
            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "email" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_create_professional_duplicate_keycloak_id_returns_409(self):
        """Test qu'un keycloak_user_id dupliqué retourne 409 Conflict."""
        professional_data = ProfessionalCreate(
            keycloak_user_id="user-123",
            first_name="Fatou",
            last_name="Sow",
            email="dr.sow@example.sn",
            phone="+221771111111",
            professional_type="physician",
            professional_id="SN-MD-67890",
            specialty="Pédiatrie",
            facility_name="Centre de Santé",
            facility_city="Dakar",
            facility_region="Dakar",
            languages_spoken="fr",
        )

        db = AsyncMock()
        current_user = {"sub": "admin-456"}

        with patch("app.services.professional_service.create_professional") as mock_create:
            mock_create.side_effect = IntegrityError(
                "INSERT INTO professionals",
                {},
                Exception("UNIQUE constraint failed: professionals.keycloak_user_id"),
            )

            with pytest.raises(HTTPException) as exc_info:
                await create_professional(professional_data, db, current_user)

            # Doit retourner 409 Conflict avec message keycloak_user_id
            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert "keycloak_user_id" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_create_professional_duplicate_professional_id_returns_409(self):
        """Test qu'un professional_id (numéro d'ordre) dupliqué retourne 409 Conflict."""
        professional_data = ProfessionalCreate(
            keycloak_user_id="user-789",
            first_name="Mamadou",
            last_name="Ba",
            email="dr.ba@example.sn",
            phone="+221772222222",
            professional_type="physician",
            professional_id="SN-MD-12345",  # Dupliqué
            specialty="Chirurgie",
            facility_name="Clinique Privée",
            facility_city="Dakar",
            facility_region="Dakar",
            languages_spoken="fr",
        )

        db = AsyncMock()
        current_user = {"sub": "admin-789"}

        with patch("app.services.professional_service.create_professional") as mock_create:
            mock_create.side_effect = IntegrityError(
                "INSERT INTO professionals",
                {},
                Exception("UNIQUE constraint failed: professionals.professional_id"),
            )

            with pytest.raises(HTTPException) as exc_info:
                await create_professional(professional_data, db, current_user)

            # Doit retourner 409 Conflict avec message professional_id
            assert exc_info.value.status_code == status.HTTP_409_CONFLICT
            assert (
                "professional_id" in exc_info.value.detail.lower()
                or "numéro d'ordre" in exc_info.value.detail.lower()
            )

    @pytest.mark.asyncio
    async def test_create_professional_success_returns_201(self):
        """Test qu'un professionnel valide est créé avec succès."""
        professional_data = ProfessionalCreate(
            keycloak_user_id="user-new",
            first_name="Ndeye",
            last_name="Diop",
            email="dr.diop@example.sn",
            phone="+221773333333",
            professional_type="physician",
            professional_id="SN-MD-99999",
            specialty="Médecine générale",
            facility_name="Centre Médical",
            facility_city="Dakar",
            facility_region="Dakar",
            languages_spoken="fr,wo",
        )

        db = AsyncMock()
        current_user = {"sub": "admin-999"}

        # Créer un objet Professional réel (pas un mock)
        mock_professional = Professional(
            id=123,
            keycloak_user_id="user-new",
            first_name="Ndeye",
            last_name="Diop",
            email="dr.diop@example.sn",
            phone="+221773333333",
            title="Dr",  # Champ requis
            professional_type="physician",
            professional_id="SN-MD-99999",
            specialty="Médecine générale",
            facility_name="Centre Médical",
            facility_city="Dakar",
            facility_region="Dakar",
            languages_spoken="fr,wo",
            is_active=True,
            is_verified=False,
            is_available=True,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        with patch("app.services.professional_service.create_professional") as mock_create:
            mock_create.return_value = mock_professional

            result = await create_professional(professional_data, db, current_user)

            # Doit retourner le professionnel créé
            assert result.id == 123
            assert result.email == "dr.diop@example.sn"
            assert result.professional_id == "SN-MD-99999"
