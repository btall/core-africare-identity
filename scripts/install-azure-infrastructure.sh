#!/bin/bash
# install-azure-infrastructure.sh
# Script d'installation de l'infrastructure Azure Event Hub pour core-africare-identity

set -e

# Configuration
RESOURCE_GROUP="rg-africare-events"
LOCATION="France Central"
NAMESPACE_NAME="evh-africare-events"
SERVICE_NAME="core-africare-identity"
STORAGE_ACCOUNT="stafricare"

echo "🚀 Installation de l'infrastructure Azure Event Hub pour $SERVICE_NAME"
echo ""

# Vérifier les prérequis
echo "🔍 Vérification des prérequis..."
if ! command -v az &> /dev/null; then
    echo "❌ Azure CLI n'est pas installé. Installez-le avec: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
    exit 1
fi

# Vérifier la connexion Azure
if ! az account show &> /dev/null; then
    echo "❌ Non connecté à Azure. Exécutez: az login"
    exit 1
fi

SUBSCRIPTION_NAME=$(az account show --query "name" -o tsv)
echo "✅ Connecté à Azure - Subscription: $SUBSCRIPTION_NAME"
echo ""

# 1. Resource Group
echo "📁 Création du Resource Group '$RESOURCE_GROUP'..."
if az group show --name $RESOURCE_GROUP &> /dev/null; then
    echo "ℹ️  Resource Group '$RESOURCE_GROUP' existe déjà"
else
    az group create \
        --name $RESOURCE_GROUP \
        --location "$LOCATION" \
        --output none
    echo "✅ Resource Group '$RESOURCE_GROUP' créé"
fi
echo ""

# 2. Storage Account pour checkpoints
echo "💾 Création du compte de stockage..."
az storage account create \
    --name $STORAGE_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --location "$LOCATION" \
    --sku "Standard_LRS" \
    --kind "StorageV2" \
    --output none
echo "✅ Compte de stockage '$STORAGE_ACCOUNT' créé"

# Container pour checkpoints
echo "📦 Création du container de checkpoints..."
az storage container create \
    --account-name $STORAGE_ACCOUNT \
    --name "eventhub-checkpoints" \
    --auth-mode login \
    --output none
echo "✅ Container 'eventhub-checkpoints' créé"
echo ""

# 3. Event Hub Namespace
echo "🏢 Création du namespace Event Hub '$NAMESPACE_NAME'..."
if az eventhubs namespace show --name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
    echo "ℹ️  Namespace '$NAMESPACE_NAME' existe déjà"
else
    az eventhubs namespace create \
        --name $NAMESPACE_NAME \
        --resource-group $RESOURCE_GROUP \
        --location "$LOCATION" \
        --sku "Basic" \
        --capacity 1 \
        --output none
    echo "✅ Namespace '$NAMESPACE_NAME' créé"
fi
echo ""

# 4. Event Hubs
echo "📡 Création des Event Hubs..."

# Event Hub principal pour le service
echo "  📢 Création de l'Event Hub principal '$SERVICE_NAME'..."
if az eventhubs eventhub show --name $SERVICE_NAME --namespace-name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
    echo "  ℹ️  Event Hub '$SERVICE_NAME' existe déjà"
else
    az eventhubs eventhub create \
        --name $SERVICE_NAME \
        --namespace-name $NAMESPACE_NAME \
        --resource-group $RESOURCE_GROUP \
        --partition-count 2 \
        --cleanup-policy Delete \
        --retention-time-in-hours 24 \
        --output none
    echo "  ✅ Event Hub '$SERVICE_NAME' créé"
fi


# Event Hub pour
echo "  📢 Création de l'Event Hub ''..."
if az eventhubs eventhub show --name "" --namespace-name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
    echo "  ℹ️  Event Hub '' existe déjà"
else
    az eventhubs eventhub create \
        --name "" \
        --namespace-name $NAMESPACE_NAME \
        --resource-group $RESOURCE_GROUP \
        --partition-count 2 \
        --cleanup-policy Delete \
        --retention-time-in-hours 24 \
        --output none
    echo "  ✅ Event Hub '' créé"
fi

echo ""

# 5. Règles d'autorisation
echo "🔐 Création des règles d'autorisation..."
POLICY_NAME="${SERVICE_NAME}-policy"
if az eventhubs namespace authorization-rule show --name $POLICY_NAME --namespace-name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP &> /dev/null; then
    echo "ℹ️  Règle d'autorisation '$POLICY_NAME' existe déjà"
else
    az eventhubs namespace authorization-rule create \
        --name $POLICY_NAME \
        --namespace-name $NAMESPACE_NAME \
        --resource-group $RESOURCE_GROUP \
        --rights Send Listen \
        --output none
    echo "✅ Règle d'autorisation '$POLICY_NAME' créée"
fi
echo ""

# 6. Récupération des connection strings
echo "🔗 Récupération des connection strings..."
echo ""

EVENTHUB_CONNECTION_STRING=$(az eventhubs namespace authorization-rule keys list \
    --name $POLICY_NAME \
    --namespace-name $NAMESPACE_NAME \
    --resource-group $RESOURCE_GROUP \
    --query "primaryConnectionString" -o tsv)

STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
    --name $STORAGE_ACCOUNT \
    --resource-group $RESOURCE_GROUP \
    --query "connectionString" -o tsv)

# 7. Génération du fichier .env
echo "📄 Génération du fichier de configuration..."
ENV_FILE=".env.azure"
cat > $ENV_FILE << EOF
# Configuration Azure Event Hub pour core-africare-identity
# Généré le $(date)

# Event Hub Configuration
AZURE_EVENTHUB_CONNECTION_STRING="$EVENTHUB_CONNECTION_STRING"
AZURE_EVENTHUB_NAMESPACE="${NAMESPACE_NAME}.servicebus.windows.net"
AZURE_EVENTHUB_NAME="$SERVICE_NAME"
AZURE_EVENTHUB_CONSUMER_GROUP="\$Default"

# Storage Configuration for Checkpoints
AZURE_EVENTHUB_BLOB_STORAGE_CONNECTION_STRING="$STORAGE_CONNECTION_STRING"
AZURE_EVENTHUB_BLOB_STORAGE_CONTAINER_NAME="eventhub-checkpoints"

# Resource Information
AZURE_RESOURCE_GROUP="$RESOURCE_GROUP"
AZURE_EVENT_HUB_NAMESPACE="$NAMESPACE_NAME"
AZURE_STORAGE_ACCOUNT="$STORAGE_ACCOUNT"
EOF

echo "✅ Configuration sauvegardée dans '$ENV_FILE'"
echo ""

# 8. Mise à jour des fichiers YAML avec yq
echo "🔧 Mise à jour des fichiers de déploiement..."

# Vérifier si yq est installé
if ! command -v yq &> /dev/null; then
    echo "⚠️  yq n'est pas installé. Installation recommandée :"
    echo "   • macOS: brew install yq"
    echo "   • Ubuntu/Debian: sudo snap install yq"
    echo "   • Ou télécharger depuis: https://github.com/mikefarah/yq/releases"
    echo ""
    echo "🔄 Mise à jour manuelle des fichiers YAML nécessaire"
else
    # Mise à jour docker-compose.yaml
    if [ -f "docker-compose.yaml" ]; then
        echo "  📝 Mise à jour docker-compose.yaml..."
        yq eval ".services.${SERVICE_NAME}.environment.AZURE_EVENTHUB_CONNECTION_STRING = \"$EVENTHUB_CONNECTION_STRING\"" -i docker-compose.yaml
        yq eval ".services.${SERVICE_NAME}.environment.AZURE_EVENTHUB_NAMESPACE = \"${NAMESPACE_NAME}.servicebus.windows.net\"" -i docker-compose.yaml
        yq eval ".services.${SERVICE_NAME}.environment.AZURE_EVENTHUB_BLOB_STORAGE_CONNECTION_STRING = \"$STORAGE_CONNECTION_STRING\"" -i docker-compose.yaml
        echo "  ✅ docker-compose.yaml mis à jour"
    else
        echo "  ℹ️  docker-compose.yaml non trouvé, ignoré"
    fi

    # Mise à jour deployment-aca.yaml
    if [ -f "deployment-aca.yaml" ]; then
        echo "  📝 Mise à jour deployment-aca.yaml..."
        yq eval ".spec.template.spec.containers[0].env[] |= select(.name == \"AZURE_EVENTHUB_CONNECTION_STRING\").value = \"$EVENTHUB_CONNECTION_STRING\"" -i deployment-aca.yaml
        yq eval ".spec.template.spec.containers[0].env[] |= select(.name == \"AZURE_EVENTHUB_NAMESPACE\").value = \"${NAMESPACE_NAME}.servicebus.windows.net\"" -i deployment-aca.yaml
        yq eval ".spec.template.spec.containers[0].env[] |= select(.name == \"AZURE_EVENTHUB_BLOB_STORAGE_CONNECTION_STRING\").value = \"$STORAGE_CONNECTION_STRING\"" -i deployment-aca.yaml
        echo "  ✅ deployment-aca.yaml mis à jour"
    else
        echo "  ℹ️  deployment-aca.yaml non trouvé, ignoré"
    fi

    echo "✅ Fichiers YAML mis à jour automatiquement"
fi
echo ""

# 9. Affichage du résumé
echo "==============================================="
echo "🎉 INSTALLATION TERMINÉE AVEC SUCCÈS !"
echo "==============================================="
echo ""
echo "📋 Ressources créées :"
echo "  • Resource Group: $RESOURCE_GROUP"
echo "  • Event Hub Namespace: $NAMESPACE_NAME"
echo "  • Event Hub principal: $SERVICE_NAME"

echo "  • Event Hub: "

echo "  • Storage Account: $STORAGE_ACCOUNT"
echo "  • Container: eventhub-checkpoints"
echo "  • Authorization Policy: $POLICY_NAME"
echo ""
echo "📁 Configuration disponible dans : $ENV_FILE"
echo ""
echo "🚀 Prochaines étapes :"
echo "  1. Copiez les variables d'environnement depuis $ENV_FILE"
echo "  2. Ajoutez-les à votre configuration (docker-compose.yml, Kubernetes, etc.)"
echo "  3. Démarrez votre service core-africare-identity"
echo ""
echo "🔍 Vérification :"
echo "  az eventhubs eventhub list --namespace-name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP --query '[].name' -o table"
echo ""

# 10. Vérification finale
echo "🧪 Test de connectivité..."
if az eventhubs eventhub show --name $SERVICE_NAME --namespace-name $NAMESPACE_NAME --resource-group $RESOURCE_GROUP --query "name" -o tsv &> /dev/null; then
    echo "✅ Test de connectivité Event Hub réussi"
else
    echo "❌ Problème de connectivité Event Hub"
    exit 1
fi

echo ""
echo "🎯 Infrastructure Azure Event Hub prête pour core-africare-identity !"
