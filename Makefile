.PHONY: install test test-unit test-integration test-all test-services-up test-services-down test-services-clean test-services-status lint lint-fix format run clean migrate migrate-up migrate-down migrate-history migrate-current migrate-docker migrate-up-docker migrate-down-docker migrate-history-docker migrate-current-docker help
.DEFAULT_GOAL := help

# Port par défaut pour uvicorn (peut être surchargé)
PORT ?= 8001
# Message par défaut pour la migration (peut être surchargé)
MESSAGE ?=

# Installation des dépendances avec Poetry
install:
	poetry install
	poetry run opentelemetry-bootstrap -a install

# ============================================================================
# Commandes de tests
# ============================================================================

# Démarrer les services Docker de test (PostgreSQL, Redis)
test-services-up:
	@echo "🚀 Démarrage des services de test..."
	docker-compose -f docker-compose.test.yaml up -d
	@echo "⏳ Attente que les services soient prêts..."
	@sleep 5
	@echo "✅ Services de test prêts!"
	@make test-services-status

# Arrêter les services Docker de test
test-services-down:
	@echo "🛑 Arrêt des services de test..."
	docker-compose -f docker-compose.test.yaml down

# Arrêter et nettoyer les volumes des services de test
test-services-clean:
	@echo "🧹 Nettoyage complet des services de test (avec volumes)..."
	docker-compose -f docker-compose.test.yaml down -v
	@echo "✅ Nettoyage terminé!"

# Vérifier le statut des services de test
test-services-status:
	@echo "📊 Statut des services de test:"
	@docker-compose -f docker-compose.test.yaml ps

# Tests unitaires uniquement (rapides, avec mocks)
test-unit:
	@echo "🧪 Lancement des tests unitaires (avec mocks)..."
	poetry run pytest tests/ -v -m "not integration" --cov=app --cov-report=term-missing

# Tests d'intégration avec vrais services Docker
test-integration:
	@echo "🧪 Lancement des tests d'intégration (avec vrais services)..."
	@echo "ℹ️  Assurez-vous que les services sont lancés: make test-services-up"
	poetry run pytest tests/ -v -m integration --cov=app --cov-report=term-missing

# Tous les tests (unitaires + intégration)
test-all: test-services-up
	@echo "🧪 Lancement de tous les tests (unitaires + intégration)..."
	poetry run pytest tests/ -v --cov=app --cov-report=term-missing --cov-report=html
	@echo "📊 Rapport de couverture HTML généré dans htmlcov/index.html"

# Lancement des tests par défaut (unitaires uniquement, rapides)
test: test-unit

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

# ============================================================================
# Database migrations (PostgreSQL only)
# ============================================================================

# --- Méthode 1: Poetry (développement local) ---

# Création d'une nouvelle migration Alembic
migrate:
	@echo "Création d'une nouvelle migration avec le message: $(MESSAGE)"
	poetry run alembic revision --autogenerate -m "$(MESSAGE)"

# Application de toutes les migrations Alembic
migrate-up:
	@echo "Application de toutes les migrations..."
	poetry run alembic upgrade head

# Annulation de la dernière migration Alembic
migrate-down:
	@echo "Rollback de la dernière migration..."
	poetry run alembic downgrade -1

# Afficher l'historique des migrations
migrate-history:
	@echo "Historique des migrations Alembic:"
	poetry run alembic history

# Afficher le statut actuel de la base de données
migrate-current:
	@echo "Statut actuel des migrations:"
	poetry run alembic current

# --- Méthode 2: Docker Compose (environnement conteneurisé) ---

# Création d'une nouvelle migration via Docker
migrate-docker:
	@echo "Création d'une nouvelle migration avec le message: $(MESSAGE)"
	docker-compose --profile migration run --rm alembic revision --autogenerate -m "$(MESSAGE)"

# Application de toutes les migrations via Docker
migrate-up-docker:
	@echo "Application de toutes les migrations via Docker..."
	docker-compose --profile migration run --rm alembic upgrade head

# Annulation de la dernière migration via Docker
migrate-down-docker:
	@echo "Rollback de la dernière migration via Docker..."
	docker-compose --profile migration run --rm alembic downgrade -1

# Afficher l'historique des migrations via Docker
migrate-history-docker:
	@echo "Historique des migrations Alembic via Docker:"
	docker-compose --profile migration run --rm alembic history

# Afficher le statut actuel via Docker
migrate-current-docker:
	@echo "Statut actuel des migrations via Docker:"
	docker-compose --profile migration run --rm alembic current

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
	@echo "📦 Installation:"
	@echo "  make install                Installer les dépendances avec Poetry"
	@echo ""
	@echo "🧪 Tests:"
	@echo "  make test                   Lancer les tests unitaires (rapide, avec mocks)"
	@echo "  make test-unit              Lancer les tests unitaires uniquement"
	@echo "  make test-integration       Lancer les tests d'intégration (vrais services)"
	@echo "  make test-all               Lancer tous les tests (unitaires + intégration)"
	@echo "  make test-services-up       Démarrer les services Docker de test"
	@echo "  make test-services-down     Arrêter les services Docker de test"
	@echo "  make test-services-clean    Nettoyer les services et volumes de test"
	@echo "  make test-services-status   Vérifier le statut des services de test"
	@echo ""
	@echo "🔍 Qualité du code:"
	@echo "  make lint                   Vérifier la qualité du code avec Ruff"
	@echo "  make lint-fix               Corriger automatiquement le code avec Ruff"
	@echo ""
	@echo "🚀 Développement:"
	@echo "  make run                    Lancer le serveur (port $(PORT))"
	@echo "                              Usage: make run PORT=8080"
	@echo ""
	@echo "🗄️  Migrations (PostgreSQL) - Méthode 1: Poetry (local):"
	@echo "  make migrate                Créer une nouvelle migration Alembic"
	@echo "                              Usage: make migrate MESSAGE='Description'"
	@echo "  make migrate-up             Appliquer toutes les migrations"
	@echo "  make migrate-down           Annuler la dernière migration"
	@echo "  make migrate-history        Afficher l'historique des migrations"
	@echo "  make migrate-current        Afficher le statut actuel de la base"
	@echo ""
	@echo "🗄️  Migrations (PostgreSQL) - Méthode 2: Docker Compose:"
	@echo "  make migrate-docker         Créer une nouvelle migration via Docker"
	@echo "                              Usage: make migrate-docker MESSAGE='Description'"
	@echo "  make migrate-up-docker      Appliquer toutes les migrations via Docker"
	@echo "  make migrate-down-docker    Annuler la dernière migration via Docker"
	@echo "  make migrate-history-docker Afficher l'historique via Docker"
	@echo "  make migrate-current-docker Afficher le statut actuel via Docker"
	@echo ""
	@echo "🧹 Nettoyage:"
	@echo "  make clean                  Nettoyer les fichiers générés et caches"
	@echo ""
	@echo "❓ Aide:"
	@echo "  make help                   Afficher cette aide"
