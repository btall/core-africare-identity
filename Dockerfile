# Utiliser une image Python officielle
FROM python:3.13-slim as builder

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY pyproject.toml ./

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Installer Poetry
RUN pip install poetry

# Installer les dépendances du projet (sans les dépendances de développement)
# Désactive la création d'environnements virtuels pour que les paquets soient installés globalement dans l'étape builder
RUN poetry config virtualenvs.create false && \
    poetry install --no-root --only main && \
    opentelemetry-bootstrap -a install

########################################################
# Deuxième étape: image d'exécution
########################################################

FROM python:3.13-slim

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Créer un utilisateur non-root
RUN addgroup --system app && adduser --system --group app

# Définir le répertoire de travail pour l'utilisateur app
WORKDIR /home/app/web

# Copier les dépendances installées depuis l'étape de build
# Copie depuis les chemins globaux de site-packages et bin de l'étape builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copier le code de l'application
# Assurez-vous que le code source est dans un sous-répertoire 'app'
COPY ./app /home/app/web/app

# Définir les permissions pour l'utilisateur app
RUN chown -R app:app /home/app/web

# Changer d'utilisateur
USER app

# Exposer le port interne de l'application
EXPOSE 8000

# Commande pour lancer l'application avec Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
