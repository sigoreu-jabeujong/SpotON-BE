"""Bounded, single-flight DB probe independent of the request connection pool."""

from threading import Lock
from time import monotonic

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings
from app.db.session import DatabaseConfigurationError, normalize_database_url

PROBE_TIMEOUT_SECONDS = 2.5
SUCCESS_TTL_SECONDS = 10
FAILURE_TTL_SECONDS = 1

PROBE_SQL = """
SELECT
  (SELECT array_agg(version_num ORDER BY version_num) FROM public.alembic_version) AS revisions,
  current_setting('default_transaction_read_only') = 'on' AS default_read_only,
  r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
    OR r.rolreplication OR r.rolbypassrls AS privileged,
  r.rolconnlimit AS connection_limit,
  pg_has_role(current_user, 'pg_write_all_data', 'MEMBER') AS write_role,
  has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create,
  has_database_privilege(current_user, current_database(), 'CREATE') AS database_create,
  has_database_privilege(current_user, current_database(), 'TEMP') AS temporary_create,
  EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
      AND has_table_privilege(current_user, c.oid,
          'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
  ) AS table_write,
  EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'S'
      AND has_sequence_privilege(current_user, c.oid, 'USAGE,UPDATE')
  ) AS sequence_write,
  EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relowner = r.oid
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
  ) AS owns_objects
FROM pg_roles r WHERE r.rolname = current_user
"""


class ReadinessProbe:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._last_result = False
        self._checked_at: float | None = None
        self._closed = False

    def _fresh(self) -> bool:
        ttl = SUCCESS_TTL_SECONDS if self._last_result else FAILURE_TTL_SECONDS
        return self._checked_at is not None and monotonic() - self._checked_at < ttl

    def check(self) -> bool:
        if self._closed:
            return False
        if self._fresh():
            return self._last_result
        if not self._lock.acquire(blocking=False):
            return self._last_result if self._fresh() else False
        try:
            if self._closed:
                return False
            if self._fresh():
                return self._last_result
            self._last_result = self._probe()
            self._checked_at = monotonic()
            return self._last_result and not self._closed
        finally:
            self._lock.release()

    def _probe(self) -> bool:
        raw = self.settings.database_url
        if raw is None:
            return False
        try:
            url = normalize_database_url(raw.get_secret_value())
            options = url.translate_connect_args(username="user", database="dbname")
            options.update(url.query)
            options["application_name"] = "spoton_ready"
            with psycopg.connect(**options, connect_timeout=1, row_factory=dict_row) as connection:
                connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                connection.read_only = True
                connection.execute("SET LOCAL statement_timeout='750ms'")
                row = connection.execute(PROBE_SQL).fetchone()
            if row is None or row["revisions"] != [self.settings.database_expected_revision]:
                return False
            if self.settings.app_env not in {"staging", "production"}:
                return True
            forbidden = (
                "privileged",
                "write_role",
                "schema_create",
                "database_create",
                "temporary_create",
                "table_write",
                "sequence_write",
                "owns_objects",
            )
            return (
                row["default_read_only"] is True
                and row["connection_limit"] >= self.settings.database_connection_budget
                and not any(row[key] for key in forbidden)
            )
        except (psycopg.Error, DatabaseConfigurationError):
            return False

    def close(self) -> None:
        # An already running probe owns at most one short-lived connection and
        # closes it itself, even if its HTTP caller times out or is cancelled.
        self._closed = True
