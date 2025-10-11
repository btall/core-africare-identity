-- Script d'initialisation de la base de données core-africare-identity
-- Exécuté automatiquement au démarrage du conteneur PostgreSQL

-- Créer l'utilisateur si nécessaire (en development seulement)
DO
$$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = 'core-africare-identity') THEN
    CREATE USER "core-africare-identity" WITH PASSWORD 'vd8bveedbnBpMcYr_8qB6A';
  END IF;
END
$$;

-- Créer la base de données
SELECT 'CREATE DATABASE "core-africare-identity" OWNER "core-africare-identity"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'core-africare-identity')\gexec

-- Accorder tous les privilèges
GRANT ALL PRIVILEGES ON DATABASE "core-africare-identity" TO "core-africare-identity";

-- Se connecter à la base de données pour créer les extensions
\c core-africare-identity

-- Créer l'extension btree_gist pour les temporal constraints (PostgreSQL 18+)
-- Permet d'utiliser EXCLUDE USING gist pour éviter les chevauchements de plages temporelles
-- Exemple: EXCLUDE USING gist (resource_id WITH =, tstzrange(start_time, end_time) WITH &&)
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Message de confirmation
\echo 'Database core-africare-identity initialized successfully'
\echo 'Extension btree_gist created for temporal constraints support'
