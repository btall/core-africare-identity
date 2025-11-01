"""
Test pour la fonction extract_token() du module security.

Vérifie que le token JWT peut être extrait de 3 sources:
1. Authorization header (Bearer token)
2. Query parameter (?token=<jwt>)
3. Cookie (auth_token)
"""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

from app.core.security import extract_token


@pytest.mark.asyncio
async def test_extract_token_from_authorization_header():
    """Test extraction du token depuis le header Authorization (priorité 1)."""
    # Arrange
    mock_request = Mock(spec=Request)
    mock_request.query_params = {}
    mock_request.cookies = {}

    mock_credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="test-token-from-header"
    )

    # Act
    token = await extract_token(mock_request, mock_credentials)

    # Assert
    assert token == "test-token-from-header"


@pytest.mark.asyncio
async def test_extract_token_from_query_parameter():
    """Test extraction du token depuis le query parameter (priorité 2)."""
    # Arrange
    mock_request = Mock(spec=Request)
    mock_request.query_params = {"token": "test-token-from-query"}
    mock_request.cookies = {}

    # Pas de credentials (pas de header Authorization)
    mock_credentials = None

    # Act
    token = await extract_token(mock_request, mock_credentials)

    # Assert
    assert token == "test-token-from-query"


@pytest.mark.asyncio
async def test_extract_token_from_cookie():
    """Test extraction du token depuis le cookie (priorité 3)."""
    # Arrange
    mock_request = Mock(spec=Request)
    mock_request.query_params = {}
    mock_request.cookies = {"auth_token": "test-token-from-cookie"}

    # Pas de credentials ni query parameter
    mock_credentials = None

    # Act
    token = await extract_token(mock_request, mock_credentials)

    # Assert
    assert token == "test-token-from-cookie"


@pytest.mark.asyncio
async def test_extract_token_priority_header_over_query():
    """Test que le header Authorization a la priorité sur le query parameter."""
    # Arrange
    mock_request = Mock(spec=Request)
    mock_request.query_params = {"token": "token-from-query"}
    mock_request.cookies = {"auth_token": "token-from-cookie"}

    mock_credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="token-from-header"
    )

    # Act
    token = await extract_token(mock_request, mock_credentials)

    # Assert
    assert token == "token-from-header"  # Header a priorité


@pytest.mark.asyncio
async def test_extract_token_priority_query_over_cookie():
    """Test que le query parameter a la priorité sur le cookie."""
    # Arrange
    mock_request = Mock(spec=Request)
    mock_request.query_params = {"token": "token-from-query"}
    mock_request.cookies = {"auth_token": "token-from-cookie"}

    # Pas de credentials
    mock_credentials = None

    # Act
    token = await extract_token(mock_request, mock_credentials)

    # Assert
    assert token == "token-from-query"  # Query a priorité sur cookie


@pytest.mark.asyncio
async def test_extract_token_no_token_found():
    """Test erreur 401 quand aucun token n'est trouvé."""
    # Arrange
    mock_request = Mock(spec=Request)
    mock_request.query_params = {}
    mock_request.cookies = {}

    mock_credentials = None

    # Act & Assert
    with pytest.raises(HTTPException) as exc_info:
        await extract_token(mock_request, mock_credentials)

    assert exc_info.value.status_code == 401
    assert "Authentication required" in exc_info.value.detail
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}


@pytest.mark.asyncio
async def test_extract_token_empty_query_parameter():
    """Test qu'un query parameter vide est ignoré."""
    # Arrange
    mock_request = Mock(spec=Request)
    mock_request.query_params = {"token": ""}  # Vide
    mock_request.cookies = {"auth_token": "token-from-cookie"}

    mock_credentials = None

    # Act
    token = await extract_token(mock_request, mock_credentials)

    # Assert
    # Query parameter vide, donc doit fallback sur cookie
    assert token == "token-from-cookie"


@pytest.mark.asyncio
async def test_extract_token_empty_cookie():
    """Test qu'un cookie vide est ignoré."""
    # Arrange
    mock_request = Mock(spec=Request)
    mock_request.query_params = {}
    mock_request.cookies = {"auth_token": ""}  # Vide

    mock_credentials = None

    # Act & Assert
    with pytest.raises(HTTPException) as exc_info:
        await extract_token(mock_request, mock_credentials)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_extract_token_sse_scenario():
    """Test scénario SSE réaliste: token en query parameter."""
    # Arrange - Simulation d'une connexion SSE
    mock_request = Mock(spec=Request)
    mock_request.query_params = {
        "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."  # JWT réaliste
    }
    mock_request.cookies = {}

    # SSE n'envoie pas de header Authorization
    mock_credentials = None

    # Act
    token = await extract_token(mock_request, mock_credentials)

    # Assert
    assert token.startswith("eyJhbGciOiJSUzI1NiI")
