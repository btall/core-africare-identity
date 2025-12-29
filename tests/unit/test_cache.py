"""Tests unitaires pour le module de cache Redis."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.cache import (
    cache_delete,
    cache_get,
    cache_key_patient,
    cache_key_professional,
    cache_key_stats_dashboard,
    cache_set,
)


class TestCacheKeyGeneration:
    """Tests pour les fonctions de generation de cles cache."""

    def test_cache_key_patient(self):
        """Test generation cle patient."""
        assert cache_key_patient(42) == "identity:patient:42"
        assert cache_key_patient(1) == "identity:patient:1"
        assert cache_key_patient(99999) == "identity:patient:99999"

    def test_cache_key_professional(self):
        """Test generation cle professional."""
        assert cache_key_professional(123) == "identity:professional:123"
        assert cache_key_professional(1) == "identity:professional:1"

    def test_cache_key_stats_dashboard(self):
        """Test generation cle dashboard."""
        assert cache_key_stats_dashboard() == "identity:stats:dashboard"


class TestCacheGet:
    """Tests pour cache_get()."""

    @pytest.mark.asyncio
    async def test_cache_get_hit(self):
        """Test cache hit retourne la valeur."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"id": 1, "name": "Test"}')

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True

                result = await cache_get("identity:patient:1")

                assert result == '{"id": 1, "name": "Test"}'
                mock_redis.get.assert_called_once_with("identity:patient:1")

    @pytest.mark.asyncio
    async def test_cache_get_miss(self):
        """Test cache miss retourne None."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True

                result = await cache_get("identity:patient:999")

                assert result is None

    @pytest.mark.asyncio
    async def test_cache_get_disabled(self):
        """Test cache disabled retourne None sans appeler Redis."""
        mock_redis = AsyncMock()

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = False

                result = await cache_get("identity:patient:1")

                assert result is None
                mock_redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_get_error_graceful_degradation(self):
        """Test erreur Redis retourne None (graceful degradation)."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis connection error"))

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True

                result = await cache_get("identity:patient:1")

                assert result is None  # Graceful degradation

    @pytest.mark.asyncio
    async def test_cache_get_no_client(self):
        """Test client None retourne None."""
        with patch("app.core.cache._get_redis_client", return_value=None):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True

                result = await cache_get("identity:patient:1")

                assert result is None


class TestCacheSet:
    """Tests pour cache_set()."""

    @pytest.mark.asyncio
    async def test_cache_set_success(self):
        """Test cache set avec TTL."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True
                mock_settings.CACHE_TTL_DEFAULT = 300

                result = await cache_set("identity:patient:1", '{"id": 1}', ttl=600)

                assert result is True
                mock_redis.set.assert_called_once_with("identity:patient:1", '{"id": 1}', ex=600)

    @pytest.mark.asyncio
    async def test_cache_set_default_ttl(self):
        """Test cache set utilise TTL par defaut si non specifie."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True
                mock_settings.CACHE_TTL_DEFAULT = 300

                result = await cache_set("identity:patient:1", '{"id": 1}')

                assert result is True
                mock_redis.set.assert_called_once_with("identity:patient:1", '{"id": 1}', ex=300)

    @pytest.mark.asyncio
    async def test_cache_set_disabled(self):
        """Test cache disabled retourne False."""
        mock_redis = AsyncMock()

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = False

                result = await cache_set("identity:patient:1", '{"id": 1}', ttl=600)

                assert result is False
                mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_set_error_graceful_degradation(self):
        """Test erreur Redis retourne False (graceful degradation)."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=Exception("Redis write error"))

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True
                mock_settings.CACHE_TTL_DEFAULT = 300

                result = await cache_set("identity:patient:1", '{"id": 1}', ttl=600)

                assert result is False  # Graceful degradation

    @pytest.mark.asyncio
    async def test_cache_set_no_client(self):
        """Test client None retourne False."""
        with patch("app.core.cache._get_redis_client", return_value=None):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True

                result = await cache_set("identity:patient:1", '{"id": 1}', ttl=600)

                assert result is False


class TestCacheDelete:
    """Tests pour cache_delete()."""

    @pytest.mark.asyncio
    async def test_cache_delete_success(self):
        """Test suppression cache."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True

                result = await cache_delete("identity:patient:1")

                assert result is True
                mock_redis.delete.assert_called_once_with("identity:patient:1")

    @pytest.mark.asyncio
    async def test_cache_delete_disabled(self):
        """Test cache disabled retourne False."""
        mock_redis = AsyncMock()

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = False

                result = await cache_delete("identity:patient:1")

                assert result is False
                mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_delete_error_graceful_degradation(self):
        """Test erreur Redis retourne False."""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(side_effect=Exception("Redis error"))

        with patch("app.core.cache._get_redis_client", return_value=mock_redis):
            with patch("app.core.cache.settings") as mock_settings:
                mock_settings.CACHE_ENABLED = True

                result = await cache_delete("identity:patient:1")

                assert result is False
