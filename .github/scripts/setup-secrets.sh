#!/usr/bin/env bash
# =============================================================================
# Script de Configuration des Secrets et Variables GitHub
# =============================================================================
#
# Ce script configure automatiquement les secrets et variables d'environnement
# GitHub Actions pour le repository core-africare-identity.
#
# Prérequis:
#   - GitHub CLI (gh) installé et authentifié: https://cli.github.com/
#   - Permissions d'écriture sur le repository
#
# Usage:
#   ./setup-secrets.sh [environment]
#
# Arguments:
#   environment  - Environnement cible: development|staging|production (défaut: development)
#
# Exemples:
#   ./setup-secrets.sh development
#   ./setup-secrets.sh staging
#   ./setup-secrets.sh production
#
# =============================================================================

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENVIRONMENT="${1:-development}"

# Couleurs pour l'affichage
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Fonctions utilitaires
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Vérifier que gh CLI est installé
check_gh_cli() {
    if ! command -v gh &> /dev/null; then
        log_error "GitHub CLI (gh) n'est pas installé"
        log_info "Installation: https://cli.github.com/"
        exit 1
    fi

    # Vérifier l'authentification
    if ! gh auth status &> /dev/null; then
        log_error "GitHub CLI n'est pas authentifié"
        log_info "Exécutez: gh auth login"
        exit 1
    fi

    log_success "GitHub CLI est installé et authentifié"
}

# Créer ou mettre à jour un secret GitHub
set_secret() {
    local secret_name="$1"
    local secret_value="$2"
    local env_name="${3:-}"

    if [[ -z "$secret_value" ]]; then
        log_warning "Valeur vide pour $secret_name - ignoré"
        return
    fi

    if [[ -n "$env_name" ]]; then
        # Secret spécifique à un environnement
        if gh secret set "$secret_name" --env "$env_name" --body "$secret_value" &> /dev/null; then
            log_success "Secret '$secret_name' configuré pour l'environnement '$env_name'"
        else
            log_error "Échec de configuration du secret '$secret_name' pour '$env_name'"
        fi
    else
        # Secret global au repository
        if gh secret set "$secret_name" --body "$secret_value" &> /dev/null; then
            log_success "Secret '$secret_name' configuré (global)"
        else
            log_error "Échec de configuration du secret '$secret_name'"
        fi
    fi
}

# Créer ou mettre à jour une variable GitHub
set_variable() {
    local var_name="$1"
    local var_value="$2"
    local env_name="${3:-}"

    if [[ -z "$var_value" ]]; then
        log_warning "Valeur vide pour $var_name - ignoré"
        return
    fi

    if [[ -n "$env_name" ]]; then
        # Variable spécifique à un environnement
        if gh variable set "$var_name" --env "$env_name" --body "$var_value" &> /dev/null; then
            log_success "Variable '$var_name' configurée pour l'environnement '$env_name'"
        else
            log_error "Échec de configuration de la variable '$var_name' pour '$env_name'"
        fi
    else
        # Variable globale au repository
        if gh variable set "$var_name" --body "$var_value" &> /dev/null; then
            log_success "Variable '$var_name' configurée (global)"
        else
            log_error "Échec de configuration de la variable '$var_name'"
        fi
    fi
}

# Charger les variables depuis un fichier .env
load_env_file() {
    local env_file="$1"

    if [[ ! -f "$env_file" ]]; then
        log_error "Fichier $env_file introuvable"
        return 1
    fi

    log_info "Chargement des variables depuis $env_file"
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
}

# Configuration des secrets et variables
configure_secrets() {
    log_info "Configuration des secrets GitHub pour l'environnement: $ENVIRONMENT"

    # Charger les variables depuis .env si disponible
    local env_file="${PROJECT_ROOT}/.env.${ENVIRONMENT}"
    if [[ -f "$env_file" ]]; then
        load_env_file "$env_file"
    else
        log_warning "Fichier $env_file introuvable - utilisation des variables d'environnement actuelles"
    fi

    # ==========================================================================
    # SECRETS (valeurs sensibles)
    # ==========================================================================

    # Keycloak Authentication
    set_secret "KEYCLOAK_SERVER_URL" "${KEYCLOAK_SERVER_URL:-}" "$ENVIRONMENT"
    set_secret "KEYCLOAK_REALM" "${KEYCLOAK_REALM:-}" "$ENVIRONMENT"
    set_secret "KEYCLOAK_CLIENT_ID" "${KEYCLOAK_CLIENT_ID:-}" "$ENVIRONMENT"
    set_secret "KEYCLOAK_CLIENT_SECRET" "${KEYCLOAK_CLIENT_SECRET:-}" "$ENVIRONMENT"

    # Database
set_secret "SQLALCHEMY_DATABASE_URI" "${SQLALCHEMY_DATABASE_URI:-}" "$ENVIRONMENT"
# Azure Event Hub
    set_secret "AZURE_EVENTHUB_CONNECTION_STRING" "${AZURE_EVENTHUB_CONNECTION_STRING:-}" "$ENVIRONMENT"
    set_secret "AZURE_EVENTHUB_BLOB_STORAGE_CONNECTION_STRING" "${AZURE_EVENTHUB_BLOB_STORAGE_CONNECTION_STRING:-}" "$ENVIRONMENT"

    # ==========================================================================
    # VARIABLES (valeurs non-sensibles)
    # ==========================================================================

    # Service Identity
    set_variable "PROJECT_NAME" "core-africare-identity"
    set_variable "PROJECT_SLUG" "identity"
    set_variable "ENVIRONMENT" "$ENVIRONMENT" "$ENVIRONMENT"

    # Azure Event Hub (configuration publique)
    set_variable "AZURE_EVENTHUB_NAMESPACE" "${AZURE_EVENTHUB_NAMESPACE:-}" "$ENVIRONMENT"
    set_variable "AZURE_EVENTHUB_NAME" "core-africare-identity" "$ENVIRONMENT"
    set_variable "AZURE_EVENTHUB_CONSUMER_GROUP" "${AZURE_EVENTHUB_CONSUMER_GROUP:-}" "$ENVIRONMENT"
    set_variable "AZURE_EVENTHUB_CONSUMER_SOURCES" "${AZURE_EVENTHUB_CONSUMER_SOURCES:-}" "$ENVIRONMENT"

    # Azure Blob Storage
    set_variable "AZURE_BLOB_STORAGE_ACCOUNT_URL" "${AZURE_BLOB_STORAGE_ACCOUNT_URL:-}" "$ENVIRONMENT"
    set_variable "AZURE_EVENTHUB_BLOB_STORAGE_CONTAINER_NAME" "${AZURE_EVENTHUB_BLOB_STORAGE_CONTAINER_NAME:-}" "$ENVIRONMENT"

    # OpenTelemetry
    set_variable "OTEL_SERVICE_NAME" "core-africare-identity" "$ENVIRONMENT"
    set_variable "OTEL_EXPORTER_OTLP_ENDPOINT" "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" "$ENVIRONMENT"
    set_variable "OTEL_EXPORTER_OTLP_PROTOCOL" "${OTEL_EXPORTER_OTLP_PROTOCOL:-grpc}" "$ENVIRONMENT"
    set_variable "OTEL_EXPORTER_OTLP_INSECURE" "${OTEL_EXPORTER_OTLP_INSECURE:-false}" "$ENVIRONMENT"

    # CORS
    set_variable "ALLOWED_ORIGINS" "${ALLOWED_ORIGINS:-}" "$ENVIRONMENT"
    set_variable "TRUSTED_HOSTS" "${TRUSTED_HOSTS:-}" "$ENVIRONMENT"

    # Internationalisation
    set_variable "SUPPORTED_LOCALES" "${SUPPORTED_LOCALES:-fr,en}" "$ENVIRONMENT"
    set_variable "DEFAULT_LOCALE" "${DEFAULT_LOCALE:-fr}" "$ENVIRONMENT"
}

# Créer les environnements GitHub si nécessaire
create_environments() {
    log_info "Création des environnements GitHub"

    for env in development staging production; do
        # gh ne permet pas de créer des environnements via CLI directement
        # Ils doivent être créés manuellement via l'interface web
        # Cette fonction sert de rappel
        log_info "Environnement '$env' - à créer manuellement si nécessaire:"
        log_info "  https://github.com/btall/core-africare-identity/settings/environments"
    done
}

# Main
main() {
    log_info "==================================================================="
    log_info "Configuration des Secrets GitHub - core-africare-identity"
    log_info "==================================================================="

    # Vérifications préalables
    check_gh_cli

    # Créer les environnements (rappel)
    create_environments

    # Configurer les secrets et variables
    configure_secrets

    log_success "==================================================================="
    log_success "Configuration terminée pour l'environnement: $ENVIRONMENT"
    log_success "==================================================================="

    log_info ""
    log_info "Prochaines étapes:"
    log_info "  1. Vérifier les secrets: gh secret list"
    log_info "  2. Vérifier les variables: gh variable list"
    log_info "  3. Configurer les autres environnements:"
    log_info "     ./setup-secrets.sh staging"
    log_info "     ./setup-secrets.sh production"
}

# Exécuter le script
main "$@"
