.PHONY: install test lint lint-fix format run clean migrate migrate-up migrate-down help
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
	@echo "  make install       Installer les dépendances"
	@echo "  make test         Lancer les tests (pytest)"
	@echo "  make lint         Vérifier la qualité du code (ruff)"
	@echo "  make lint-fix     Corriger automatiquement le code (ruff)"
	@echo "  make run          Lancer le serveur de développement (uvicorn sur port $(PORT))"
	@echo "                    (Utiliser 'make run PORT=XXXX' pour changer le port)"
@echo "  make migrate      Créer une nouvelle migration (alembic)"
	@echo "                    (Utiliser 'make migrate MESSAGE="Mon message"')"
	@echo "  make migrate-up   Appliquer les migrations (alembic)"
	@echo "  make migrate-down Annuler la dernière migration (alembic)"
@echo "  make clean        Nettoyer les fichiers générés et caches"
	@echo "  make help         Afficher cette aide"
