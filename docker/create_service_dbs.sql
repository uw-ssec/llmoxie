-- Create Service Databases
--
-- Usage:
--   psql -U $POSTGRES_USER -f create_service_dbs.sql
--
-- Note: This script is idempotent and can be run multiple times safely.

-- Create the mlflow_db database if it doesn't exist
SELECT 'CREATE DATABASE mlflow_db'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow_db')\gexec

-- Grant all privileges on mlflow_db to the POSTGRES_USER
-- Note: Replace ${POSTGRES_USER} with the actual username when running manually,
-- or use the environment variable if running through docker-compose
\c mlflow_db

-- Grant privileges to the database owner
GRANT ALL PRIVILEGES ON DATABASE mlflow_db TO CURRENT_USER;

-- Grant default privileges for future tables and sequences
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO CURRENT_USER;

-- Display confirmation
\echo 'Successfully created mlflow_db and granted privileges'
\echo 'Database: mlflow_db'
\echo 'Owner: ' :USER

-- Create the litellm_db database if it doesn't exist
SELECT 'CREATE DATABASE litellm_db'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'litellm_db')\gexec

-- Grant all privileges on litellm_db to the POSTGRES_USER
-- Note: Replace ${POSTGRES_USER} with the actual username when running manually,
-- or use the environment variable if running through docker-compose
\c litellm_db

-- Grant privileges to the database owner
GRANT ALL PRIVILEGES ON DATABASE litellm_db TO CURRENT_USER;

-- Grant default privileges for future tables and sequences
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO CURRENT_USER;

-- Display confirmation
\echo 'Successfully created litellm_db and granted privileges'
\echo 'Database: litellm_db'
\echo 'Owner: ' :USER