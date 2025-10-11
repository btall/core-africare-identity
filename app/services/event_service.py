"""Service de gestion des événements avec Azure Event Hub."""
import logging
from typing import Optional

from azure.eventhub.aio import EventHubConsumerClient, EventHubProducerClient
from azure.eventhub import EventData
from azure.eventhub.extensions.checkpointstoreblobaio import BlobCheckpointStore

from app.core.config import settings
from app.events import get_event_handler

logger = logging.getLogger(__name__)

checkpoint_store = BlobCheckpointStore.from_connection_string(
    conn_str=settings.AZURE_EVENTHUB_BLOB_STORAGE_CONNECTION_STRING,
    container_name=settings.AZURE_EVENTHUB_BLOB_STORAGE_CONTAINER_NAME,
)

# Création de tous les clients producteurs
producer_client_core_africare_identity = EventHubProducerClient.from_connection_string(
    conn_str=settings.AZURE_EVENTHUB_CONNECTION_STRING,
    eventhub_name=settings.AZURE_EVENTHUB_NAME,
)

# Fonctions d'envoi d'événements
async def send_event_core_africare_identity(event: EventData, partition_key: Optional[str] = None):
    """Envoie un événement sur le topic core-africare-identity."""
    await producer_client_core_africare_identity.send_event(event, partition_key=partition_key)




################################################################################
# Consumer pour les événements du topic 
################################################################################

async def start_eventhub_consumer_():
    """Démarre le consommateur d'événements pour le topic ."""
    # Récupérer les handlers depuis le registry
    on_event_handler = get_event_handler("", "on_event")
    on_error_handler = get_event_handler("", "on_error")

    if not on_event_handler or not on_error_handler:
        logger.error(f"Handlers manquants pour l'événement ")
        return

    client = EventHubConsumerClient.from_connection_string(
        conn_str=settings.AZURE_EVENTHUB_CONNECTION_STRING,
        consumer_group=settings.AZURE_EVENTHUB_CONSUMER_GROUP,
        eventhub_name="",
        checkpoint_store=checkpoint_store,
    )

    async with client:
        await client.receive(
            on_event=on_event_handler,
            on_error=on_error_handler,
        )

