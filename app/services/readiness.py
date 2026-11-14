"""Bounded, single-flight DB probe independent of the request connection pool."""

from concurrent.futures import Future
from threading import Lock
from time import monotonic

import psycopg
from psycopg.rows import dict_row

from app.core.config import Settings
from app.core.operations import ReadinessReason, readiness_probe
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
        self._current: Future[bool] | None = None

    def _fresh(self) -> bool:
        ttl = SUCCESS_TTL_SECONDS if self._last_result else FAILURE_TTL_SECONDS
        return self._checked_at is not None and monotonic() - self._checked_at < ttl

    def check(self) -> bool:
        started = monotonic()
        deadline = started + PROBE_TIMEOUT_SECONDS
        with self._lock:
            if self._closed:
                return False
            if self._current is not None:
                future = self._current
                owner = False
            elif self._fresh():
                return self._last_result
            else:
                future = Future()
                future.set_running_or_notify_cancel()
                self._current = future
                owner = True

        if owner:
            reason: ReadinessReason = "internal_error"
            try:
                reason = self._probe()
            except Exception:
                # Fail closed without keeping or emitting raw exception details.
                pass
            finally:
                duration = round((monotonic() - started) * 1000, 3)
                self._complete(future, reason == "ok")
                readiness_probe(reason=reason, duration=duration)
            result = reason == "ok"
        else:
            try:
                result = future.result(timeout=max(0, deadline - monotonic()))
            except TimeoutError:
                return False
        with self._lock:
            return result and not self._closed

    def _complete(self, future: Future[bool], result: bool) -> None:
        with self._lock:
            if self._current is not future:
                return
            self._current = None
            if not self._closed:
                self._last_result = result
                self._checked_at = monotonic()
        # Callbacks and logging must never run under the state lock.
        future.set_result(result)

    def _probe(self) -> ReadinessReason:
        raw = self.settings.database_url
        if raw is None:
            return "configuration_missing"
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
                return "revision_mismatch"
            if self.settings.app_env not in {"staging", "production"}:
                return "ok"
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
            if row["connection_limit"] < self.settings.database_connection_budget:
                return "connection_limit"
            if row["default_read_only"] is not True or any(row[key] for key in forbidden):
                return "unsafe_role"
            return "ok"
        except DatabaseConfigurationError:
            return "configuration_invalid"
        except psycopg.Error as exc:
            return "query_cancelled" if exc.sqlstate == "57014" else "database_error"

    def close(self) -> None:
        # An already running probe owns at most one short-lived connection and
        # closes it itself, even if its HTTP caller times out or is cancelled.
        with self._lock:
            self._closed = True
            self._last_result = False
            self._checked_at = None
            future = self._current
            self._current = None
        if future is not None:
            future.set_result(False)
