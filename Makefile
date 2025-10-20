.PHONY: install test test-unit test-integration test-all test-services-up test-services-down test-services-clean test-services-status lint lint-fix format run clean migrate migrate-up migrate-down migrate-docker help
.DEFAULT_GOAL := help

# Port par défaut pour uvicorn (peut être surchargé)
PORT ?= 8001
# Message par défaut pour la migration (peut être surchargé)
MESSAGE ?=

# Installation des dépendances avec Poetry
install:
	poetry install
	poetry run opentelemetry-bootstrap -a install

# Lancement des tests avec pytest (ajuster le chemin des tests si nécessaire)
test:
	poetry run pytest tests/ -v --cov=app --cov-report=term-missing

# Tests unitaires uniquement (sans services Docker)
test-unit:
	@echo "🧪 Exécution des tests unitaires (sans services Docker)..."
	poetry run pytest tests/ -v -m "not integration" --cov=app --cov-report=term-missing

# Tests d'intégration uniquement (avec services Docker)
test-integration:
	@echo "🧪 Exécution des tests d'intégration (nécessite services Docker)..."
	poetry run pytest tests/ -v -m integration --cov=app --cov-report=term-missing

# Tous les tests (unitaires + intégration) avec rapport HTML
test-all: test-services-up
	@echo "🧪 Exécution de tous les tests..."
	poetry run pytest tests/ -v --cov=app --cov-report=html --cov-report=term-missing
	@echo "📊 Rapport de couverture disponible dans htmlcov/index.html"
	@echo "🛑 Arrêt des services de test..."
	@make test-services-down

# Démarrer les services de test Docker
test-services-up:
	@echo "🚀 Démarrage des services de test..."
	docker-compose -f docker-compose.test.yaml up -d
	@echo "⏳ Attente de la disponibilité des services..."
	@sleep 5
	@make test-services-status

# Arrêter les services de test Docker
test-services-down:
	@echo "🛑 Arrêt des services de test..."
	docker-compose -f docker-compose.test.yaml down

# Nettoyer complètement les services de test (avec volumes)
test-services-clean:
	@echo "🧹 Nettoyage complet des services de test (avec volumes)..."
	docker-compose -f docker-compose.test.yaml down -v

# Vérifier le statut des services de test
test-services-status:
	@echo "📊 Statut des services de test:"
	@docker-compose -f docker-compose.test.yaml ps

# Vérification du code avec Ruff (sans modification)
lint:
	poetry run ruff check .
	poetry run ruff format --check .
	# Décommenter si vous utilisez mypy pour l'analyse statique de types
	# poetry run mypy .

# Correction automatique du code avec Ruff
lint-fix:
	poetry run ruff check . --fix
	poetry run ruff format .

# Lancement du serveur de développement Uvicorn
run:
	@echo "Lancement du serveur sur http://0.0.0.0:$(PORT)"
	poetry run uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

# Database migrations (PostgreSQL only)
# Création d'une nouvelle migration Alembic
migrate:
	@echo "Création d'une nouvelle migration avec le message: $(MESSAGE)"
	poetry run alembic revision --autogenerate -m "$(MESSAGE)"

# Application des migrations Alembic
migrate-up:
	poetry run alembic upgrade head

# Annulation de la dernière migration Alembic
migrate-down:
	poetry run alembic downgrade -1

# Application des migrations via Docker (sans installation locale)
migrate-docker:
	@echo "Application des migrations via Docker..."
	docker-compose run --rm migrate

# Nettoyage complet des fichiers temporaires et générés
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "*.egg" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type d -name "build" -exec rm -rf {} +
	find . -type d -name "dist" -exec rm -rf {} +

# Affichage de l'aide
help:
	@echo "Commandes Makefile disponibles pour core-africare-identity:"
	@echo ""
	@echo "Installation et développement:"
	@echo "  make install              Installer les dépendances"
	@echo "  make run                  Lancer le serveur de développement (uvicorn sur port $(PORT))"
	@echo "                            (Utiliser 'make run PORT=XXXX' pour changer le port)"
	@echo ""
	@echo "Tests:"
	@echo "  make test                 Lancer tous les tests (unitaires avec mocks)"
	@echo "  make test-unit            Lancer uniquement les tests unitaires (rapides, sans Docker)"
	@echo "  make test-integration     Lancer uniquement les tests d'intégration (avec Docker)"
	@echo "  make test-all             Lancer tous les tests + générer rapport HTML"
	@echo ""
	@echo "Services de test Docker:"
	@echo "  make test-services-up     Démarrer les services de test (PostgreSQL, Redis)"
	@echo "  make test-services-down   Arrêter les services de test"
	@echo "  make test-services-clean  Nettoyer les services de test (avec volumes)"
	@echo "  make test-services-status Vérifier le statut des services de test"
	@echo ""
	@echo "Qualité du code:"
	@echo "  make lint                 Vérifier la qualité du code (ruff)"
	@echo "  make lint-fix             Corriger automatiquement le code (ruff)"
	@echo ""
	@echo "Migrations de base de données:"
	@echo "  make migrate              Créer une nouvelle migration (alembic)"
	@echo "                            (Utiliser 'make migrate MESSAGE=\"Mon message\"')"
	@echo "  make migrate-up           Appliquer les migrations (alembic - local)"
	@echo "  make migrate-down         Annuler la dernière migration (alembic - local)"
	@echo "  make migrate-docker       Appliquer les migrations via Docker (sans Poetry local)"
	@echo ""
	@echo "Utilitaires:"
	@echo "  make clean                Nettoyer les fichiers générés et caches"
	@echo "  make help                 Afficher cette aide"
