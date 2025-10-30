"""
Tests d'intégration Redis pour core-africare-identity.

Ces tests utilisent un vrai Redis 7 sur le port 6380 (docker-compose.test.yaml).
"""

import asyncio

import pytest
from redis.asyncio import Redis


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_connection(redis_client: Redis):
    """Test connexion basique à Redis."""
    # Test PING
    response = await redis_client.ping()
    assert response is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_set_get(redis_client: Redis):
    """Test opérations SET et GET."""
    # Set value
    await redis_client.set("test_key", "test_value")

    # Get value
    value = await redis_client.get("test_key")
    assert value == "test_value"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_set_with_expiration(redis_client: Redis):
    """Test SET avec expiration (TTL)."""
    # Set avec expiration de 2 secondes
    await redis_client.set("expiring_key", "temporary_value", ex=2)

    # Vérifier que la clé existe
    value = await redis_client.get("expiring_key")
    assert value == "temporary_value"

    # Vérifier le TTL
    ttl = await redis_client.ttl("expiring_key")
    assert 0 < ttl <= 2

    # Attendre expiration
    await asyncio.sleep(2.5)

    # Vérifier que la clé a expiré
    value_after_expiration = await redis_client.get("expiring_key")
    assert value_after_expiration is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_hash_operations(redis_client: Redis):
    """Test opérations HASH (HSET, HGET, HGETALL)."""
    # HSET multiple fields
    patient_data = {
        "id": "patient-123",
        "first_name": "Amadou",
        "last_name": "Diallo",
        "email": "amadou.diallo@example.sn",
    }

    await redis_client.hset("patient:123", mapping=patient_data)

    # HGET single field
    first_name = await redis_client.hget("patient:123", "first_name")
    assert first_name == "Amadou"

    # HGETALL
    all_data = await redis_client.hgetall("patient:123")
    assert all_data["id"] == "patient-123"
    assert all_data["first_name"] == "Amadou"
    assert all_data["last_name"] == "Diallo"
    assert all_data["email"] == "amadou.diallo@example.sn"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_list_operations(redis_client: Redis):
    """Test opérations LIST (LPUSH, RPUSH, LRANGE)."""
    # LPUSH (ajout à gauche)
    await redis_client.lpush("events", "event1", "event2", "event3")

    # LRANGE (récupérer tous les éléments)
    events = await redis_client.lrange("events", 0, -1)
    assert len(events) == 3
    assert events[0] == "event3"  # LPUSH inverse l'ordre
    assert events[1] == "event2"
    assert events[2] == "event1"

    # RPUSH (ajout à droite)
    await redis_client.rpush("events", "event4")
    events = await redis_client.lrange("events", 0, -1)
    assert len(events) == 4
    assert events[3] == "event4"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_pub_sub(redis_client: Redis):
    """Test Publish/Subscribe."""
    # Créer un subscriber
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("identity.events")

    # Publier un message
    await redis_client.publish("identity.events", "patient.created")

    # Attendre les messages
    # Premier message = confirmation de subscription
    message1 = await pubsub.get_message(timeout=1.0)
    assert message1["type"] == "subscribe"

    # Deuxième message = notre événement
    message2 = await pubsub.get_message(timeout=1.0)
    assert message2["type"] == "message"
    assert message2["data"] == "patient.created"

    # Cleanup
    await pubsub.unsubscribe("identity.events")
    await pubsub.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_incr_decr(redis_client: Redis):
    """Test opérations INCR et DECR (compteurs)."""
    # INCR
    count = await redis_client.incr("patient_count")
    assert count == 1

    count = await redis_client.incr("patient_count")
    assert count == 2

    # INCRBY
    count = await redis_client.incrby("patient_count", 5)
    assert count == 7

    # DECR
    count = await redis_client.decr("patient_count")
    assert count == 6


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_set_operations(redis_client: Redis):
    """Test opérations SET (SADD, SMEMBERS, SISMEMBER)."""
    # SADD (ajouter membres)
    await redis_client.sadd("active_patients", "patient-1", "patient-2", "patient-3")

    # SMEMBERS (récupérer tous les membres)
    members = await redis_client.smembers("active_patients")
    assert len(members) == 3
    assert "patient-1" in members
    assert "patient-2" in members
    assert "patient-3" in members

    # SISMEMBER (vérifier appartenance) - Redis renvoie 1 ou 0, pas True/False
    is_member = await redis_client.sismember("active_patients", "patient-1")
    assert is_member == 1  # Redis renvoie 1 pour True

    is_not_member = await redis_client.sismember("active_patients", "patient-999")
    assert is_not_member == 0  # Redis renvoie 0 pour False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_delete_keys(redis_client: Redis):
    """Test suppression de clés."""
    # Créer plusieurs clés
    await redis_client.set("key1", "value1")
    await redis_client.set("key2", "value2")
    await redis_client.set("key3", "value3")

    # Vérifier existence
    assert await redis_client.exists("key1") == 1
    assert await redis_client.exists("key2") == 1

    # Supprimer une clé
    deleted = await redis_client.delete("key1")
    assert deleted == 1

    # Vérifier suppression
    assert await redis_client.exists("key1") == 0
    assert await redis_client.exists("key2") == 1

    # Supprimer plusieurs clés
    deleted = await redis_client.delete("key2", "key3")
    assert deleted == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_cache_pattern(redis_client: Redis):
    """Test pattern de cache typique : get-or-set."""

    async def get_or_cache_patient(patient_id: str) -> dict:
        """Simule récupération depuis cache ou DB."""
        cache_key = f"patient_cache:{patient_id}"

        # Essayer de récupérer depuis le cache
        cached_data = await redis_client.hgetall(cache_key)
        if cached_data:
            return cached_data

        # Simuler récupération depuis DB
        patient_data = {
            "id": patient_id,
            "first_name": "Fatou",
            "last_name": "Sall",
            "email": "fatou.sall@example.sn",
        }

        # Mettre en cache (TTL 1 heure)
        await redis_client.hset(cache_key, mapping=patient_data)
        await redis_client.expire(cache_key, 3600)

        return patient_data

    # Premier appel : cache miss, récupère depuis "DB"
    data1 = await get_or_cache_patient("123")
    assert data1["id"] == "123"
    assert data1["first_name"] == "Fatou"

    # Deuxième appel : cache hit
    data2 = await get_or_cache_patient("123")
    assert data2["id"] == "123"
    assert data2["first_name"] == "Fatou"
    assert data1 == data2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_pipeline(redis_client: Redis):
    """Test utilisation de pipeline pour batch operations."""
    # Créer un pipeline
    async with redis_client.pipeline() as pipe:
        # Batch de commandes
        pipe.set("pipe_key1", "value1")
        pipe.set("pipe_key2", "value2")
        pipe.incr("pipe_counter")
        pipe.incr("pipe_counter")

        # Exécuter le batch
        results = await pipe.execute()

    # Vérifier résultats
    assert results[0] is True  # SET key1
    assert results[1] is True  # SET key2
    assert results[2] == 1  # INCR counter (1)
    assert results[3] == 2  # INCR counter (2)

    # Vérifier valeurs
    value1 = await redis_client.get("pipe_key1")
    assert value1 == "value1"

    counter = await redis_client.get("pipe_counter")
    assert counter == "2"
