import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.core.database import Base

# Importer tous les modèles pour qu'Alembic puisse les détecter
from app.models import *  # noqa: F403

# config = context.config object
config = context.config

# Interpréter le fichier de configuration pour Python logging.
# Cette ligne assume que le fichier de configuration s'appelle 'alembic.ini'
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Ajouter ici les métadonnées de vos modèles pour 'autogenerate' support
# SQLAlchemy utilise Base.metadata
target_metadata = Base.metadata


def get_url():
    # Utiliser les settings pour obtenir l'URL de la base de données
    return settings.SQLALCHEMY_DATABASE_URI.unicode_string()


def run_migrations_offline() -> None:
    """Exécute les migrations en mode 'offline'.

    Ceci configure le contexte uniquement avec une URL
    et non un Engine, bien qu'un Engine soit également acceptable
    ici. En sautant la création de l'Engine, nous n'avons même pas besoin
    d'une API DB disponible.

    Les appels à context.execute() émettent la DDL donnée vers la sortie script.

    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Activer la comparaison de types
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,  # Activer la comparaison de types
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Exécute les migrations en mode 'online'.

    Dans ce scénario, nous avons besoin de créer un Engine
    et d'associer une connexion avec le contexte.

    """
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Exécute les migrations en mode 'online'."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    # Offline mode n'est pas géré pour l'asyncio
    # raise NotImplementedError("Les migrations hors ligne ne sont pas supportées pour l'asyncio")
    # On utilise la version synchrone pour le mode offline
    run_migrations_offline()
else:
    run_migrations_online()
