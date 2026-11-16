from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from app.core.errors import AppError
from app.db import dependencies as db


def setup_sessions(monkeypatch, failures, *, setup_error=None):
    events = []
    sessions = []

    class FakeSession:
        def __init__(self, engine):
            self.index = len(sessions)
            sessions.append(self)

        def connection(self, **kwargs):
            events.append((self.index, "checkout"))
            if self.index < len(failures) and failures[self.index]:
                raise failures[self.index]

        def execute(self, *args):
            events.append((self.index, "setup"))
            if setup_error:
                raise setup_error

        def close(self):
            events.append((self.index, "close"))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    monkeypatch.setattr(db, "Session", FakeSession)
    resources = SimpleNamespace(
        get_engine=lambda: object(), settings=SimpleNamespace(database_statement_timeout_ms=10000)
    )
    return resources, sessions, events


def test_retries_checkout_once_after_closing_failed_session(monkeypatch):
    resources, sessions, events = setup_sessions(monkeypatch, [PoolTimeout("synthetic")])
    with db.read_only_session(resources, pool_retries=1) as session:
        events.append((session.index, "body"))
    assert len(sessions) == 2
    assert events.index((0, "close")) < events.index((1, "checkout"))
    assert events.count((1, "body")) == 1
    assert events.count((1, "setup")) == 2
    assert events[-1] == (1, "close")


@pytest.mark.parametrize("retries,expected", [(0, 1), (1, 2)])
def test_default_and_exhaustion_are_bounded(monkeypatch, retries, expected):
    resources, sessions, events = setup_sessions(monkeypatch, [PoolTimeout("synthetic")] * 2)
    with pytest.raises(AppError):
        with db.read_only_session(resources, pool_retries=retries):
            pytest.fail("body must not execute")
    assert len(sessions) == expected
    assert sum(event == "close" for _, event in events) == expected


@pytest.mark.parametrize(
    "failure", [OperationalError("synthetic", {}, Exception()), TimeoutError("synthetic")]
)
def test_non_pool_checkout_failure_is_not_retried(monkeypatch, failure):
    resources, sessions, events = setup_sessions(monkeypatch, [failure])
    with pytest.raises((AppError, TimeoutError)):
        with db.read_only_session(resources, pool_retries=1):
            pytest.fail("body must not execute")
    assert len(sessions) == 1
    assert events[-1] == (0, "close")


def test_setup_failure_is_not_retried(monkeypatch):
    resources, sessions, _ = setup_sessions(monkeypatch, [], setup_error=PoolTimeout("synthetic"))
    with pytest.raises(AppError):
        with db.read_only_session(resources, pool_retries=1):
            pytest.fail("body must not execute")
    assert len(sessions) == 1


def test_body_failure_is_not_replayed(monkeypatch):
    resources, sessions, events = setup_sessions(monkeypatch, [])
    with pytest.raises(AppError):
        with db.read_only_session(resources, pool_retries=1) as session:
            events.append((session.index, "body"))
            raise PoolTimeout("synthetic body error")
    assert len(sessions) == 1
    assert events.count((0, "body")) == 1
