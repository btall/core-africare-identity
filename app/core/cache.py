"""
Module de cache Redis pour core-africare-identity.

Strategie Cache-Aside (Lazy Loading) avec TTL-only invalidation.
Les erreurs cache ne cassent jamais l'application (graceful degradation).

Usage:
    from app.core.cache import cache_get, cache_set, cache_key_patient

    # Lecture cache
    cached = await cache_get("identity:patient:42")
    if cached:
        return PatientResponse.model_validate_json(cached)

    # Ecriture cache
    await cache_set("identity:patient:42", response.model_dump_json(), ttl=600)
"""

import logging
import time

from opentelemetry import metrics

from app.core.config import settings

logger = logging.getLogger(__name__)

# OpenTelemetry Metrics
meter = metrics.get_meter("core-africare-identity.cache")

cache_hits_counter = meter.create_counter(
    name="cache_hits_total",
    description="Total number of cache hits",
    unit="1",
)

cache_misses_counter = meter.create_counter(
    name="cache_misses_total",
    description="Total number of cache misses",
    unit="1",
)

cache_latency_histogram = meter.create_histogram(
    name="cache_latency_seconds",
    description="Cache operation latency in seconds",
    unit="s",
)


def _get_redis_client():
    """
    Recupere le client Redis global depuis events_redis.

    Returns:
        Client Redis ou None si non initialise
    """
    from app.core.events_redis import redis_client

    return redis_client


def _extract_key_prefix(key: str) -> str:
    """Extrait le prefix de la cle pour les labels de metriques."""
    parts = key.split(":")
    if len(parts) >= 2:
        return parts[1]  # identity:patient:42 -> patient
    return "unknown"


async def cache_get(key: str) -> str | None:
    """
    Lit une valeur depuis le cache Redis.

    Args:
        key: Cle du cache (ex: "identity:patient:42")

    Returns:
        Valeur JSON ou None si non trouve/erreur

    Note:
        Les erreurs Redis sont loguees mais ne propagent pas (graceful degradation)
    """
    if not settings.CACHE_ENABLED:
        return None

    redis_client = _get_redis_client()
    if not redis_client:
        logger.warning("Redis client non initialise, cache desactive")
        return None

    key_prefix = _extract_key_prefix(key)
    start_time = time.perf_counter()

    try:
        value = await redis_client.get(key)
        latency = time.perf_counter() - start_time

        # Enregistrer metriques
        cache_latency_histogram.record(latency, {"operation": "get", "key_prefix": key_prefix})

        if value:
            cache_hits_counter.add(1, {"key_prefix": key_prefix})
            logger.debug(f"Cache HIT: {key}")
            return value
        else:
            cache_misses_counter.add(1, {"key_prefix": key_prefix})
            logger.debug(f"Cache MISS: {key}")
            return None

    except Exception as e:
        # Graceful degradation: erreur cache = cache miss
        latency = time.perf_counter() - start_time
        cache_latency_histogram.record(latency, {"operation": "get", "key_prefix": "error"})
        cache_misses_counter.add(1, {"key_prefix": "error"})
        logger.warning(f"Cache GET error pour {key}: {e}")
        return None


async def cache_set(key: str, value: str, ttl: int | None = None) -> bool:
    """
    Ecrit une valeur dans le cache Redis avec TTL.

    Args:
        key: Cle du cache
        value: Valeur JSON a cacher
        ttl: Time-to-live en secondes (utilise CACHE_TTL_DEFAULT si None)

    Returns:
        True si succes, False sinon

    Note:
        Les erreurs Redis sont loguees mais ne propagent pas
    """
    if not settings.CACHE_ENABLED:
        return False

    redis_client = _get_redis_client()
    if not redis_client:
        logger.warning("Redis client non initialise, cache desactive")
        return False

    ttl = ttl or settings.CACHE_TTL_DEFAULT
    key_prefix = _extract_key_prefix(key)
    start_time = time.perf_counter()

    try:
        await redis_client.set(key, value, ex=ttl)
        latency = time.perf_counter() - start_time

        cache_latency_histogram.record(latency, {"operation": "set", "key_prefix": key_prefix})
        logger.debug(f"Cache SET: {key} (TTL: {ttl}s)")
        return True

    except Exception as e:
        latency = time.perf_counter() - start_time
        cache_latency_histogram.record(latency, {"operation": "set", "key_prefix": "error"})
        logger.warning(f"Cache SET error pour {key}: {e}")
        return False


async def cache_delete(key: str) -> bool:
    """
    Supprime une cle du cache (optionnel, pour invalidation manuelle).

    Args:
        key: Cle a supprimer

    Returns:
        True si supprime, False sinon
    """
    if not settings.CACHE_ENABLED:
        return False

    redis_client = _get_redis_client()
    if not redis_client:
        return False

    key_prefix = _extract_key_prefix(key)
    start_time = time.perf_counter()

    try:
        await redis_client.delete(key)
        latency = time.perf_counter() - start_time

        cache_latency_histogram.record(latency, {"operation": "delete", "key_prefix": key_prefix})
        logger.debug(f"Cache DELETE: {key}")
        return True

    except Exception as e:
        latency = time.perf_counter() - start_time
        cache_latency_histogram.record(latency, {"operation": "delete", "key_prefix": "error"})
        logger.warning(f"Cache DELETE error pour {key}: {e}")
        return False


# =============================================================================
# Cache Key Generators
# =============================================================================


def cache_key_patient(patient_id: int) -> str:
    """
    Genere la cle cache pour un patient.

    Args:
        patient_id: ID numerique du patient

    Returns:
        Cle au format "identity:patient:{id}"
    """
    return f"identity:patient:{patient_id}"


def cache_key_professional(professional_id: int) -> str:
    """
    Genere la cle cache pour un professionnel.

    Args:
        professional_id: ID numerique du professionnel

    Returns:
        Cle au format "identity:professional:{id}"
    """
    return f"identity:professional:{professional_id}"


def cache_key_stats_dashboard() -> str:
    """
    Genere la cle cache pour le dashboard statistiques.

    Returns:
        Cle "identity:stats:dashboard"
    """
    return "identity:stats:dashboard"


__all__ = [
    "cache_delete",
    "cache_get",
    "cache_key_patient",
    "cache_key_professional",
    "cache_key_stats_dashboard",
    "cache_set",
]
