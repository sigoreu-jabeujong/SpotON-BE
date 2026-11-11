#!/bin/sh
set -eu

# Runs only when Docker initializes an empty development data volume.
# The PostGIS image enables the extension before this script runs.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=ON_ERROR_STOP=1 --set=app_password="$SPOTON_DB_PASSWORD" <<'SQL'
CREATE ROLE spoton_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION PASSWORD :'app_password';
GRANT CONNECT ON DATABASE spoton_dev TO spoton_app;
GRANT USAGE, CREATE ON SCHEMA public TO spoton_app;
SQL
