"""Database engine and session management."""

from __future__ import annotations

import os
from typing import cast

from sqlalchemy import create_engine, event
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.expression import Executable

DEFAULT_DATABASE_URL = "sqlite:///conflicts.db"

# How long a writer waits for a competing writer before raising "database is
# locked". The API writes from the threadpool while the daily pipeline writes to
# the same file; with SQLite's default (0 ms) the loser fails immediately and a
# concurrent PATCH turns into a 500.
BUSY_TIMEOUT_MS = 5000


def database_url() -> str:
    """Resolve the database URL at call time.

    Reading the environment at import time meant `GCM_DATABASE_URL` had to be set
    before any `app.*` import — true for a process start, silently false for a
    test or a script that configures the connection itself.
    """
    return os.environ.get("GCM_DATABASE_URL", DEFAULT_DATABASE_URL)


# Kept for Alembic's env.py, which imports a name rather than calling a function.
SQLITE_URL = DEFAULT_DATABASE_URL


def make_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if not url.startswith("sqlite"):
        return create_engine(url, future=True)

    # `timeout=0` on purpose: pysqlite otherwise installs its own 5 s busy
    # handler, which would make the `busy_timeout` pragma below a no-op and its
    # test pass without exercising it. The pragma is set on connect, so it is the
    # single source of the wait — and it can be tuned in one place.
    engine = create_engine(
        url,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 0},
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        # Referential integrity is off in SQLite by default; the models rely on it.
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets readers continue while the pipeline writes (and vice versa)
        # instead of failing with "database is locked". It is persistent per
        # database file, so this is a no-op after the first connection; an
        # in-memory database answers "memory" and stays a rollback journal.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


# Built on first use, not at import: the URL comes from the environment, and an
# import-time engine pins whatever value was there when `app.db` was first
# imported. A single lazy pair keeps sessions in one pool for the process.
_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session() -> Session:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(get_engine())
    return _session_factory()


def execute_dml(session: Session, stmt: Executable) -> int:
    """Run an INSERT/UPDATE/DELETE and return its affected row count.

    `Session.execute` is typed as returning `Result`, which has no `rowcount`; for
    DML it actually returns a `CursorResult`. The cast lies only to the type
    checker — the runtime object genuinely is a CursorResult.
    """
    result = cast(CursorResult, session.execute(stmt))
    return max(0, result.rowcount or 0)
