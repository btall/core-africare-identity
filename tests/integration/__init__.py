"""
Tests d'intégration pour core-africare-identity.

Ces tests utilisent de vrais services Docker (PostgreSQL, Redis) sur des ports exotiques
pour éviter les conflits avec les services de développement.

Usage:
    # Démarrer les services
    make test-services-up

    # Lancer les tests d'intégration
    make test-integration

    # Arrêter les services
    make test-services-down
"""
