"""Database engine and session management."""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

SQLITE_URL = os.environ.get("GCM_DATABASE_URL", "sqlite:///conflicts.db")


def make_engine(url: str = SQLITE_URL) -> Engine:
    if url.startswith("sqlite"):
        return create_engine(url, future=True, connect_args={"check_same_thread": False})
    return create_engine(url, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


engine = make_engine()
SessionLocal = make_session_factory(engine)


def get_session() -> Session:
    return SessionLocal()
