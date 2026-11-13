"""Shared SQLAlchemy connection and query helpers."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)
load_dotenv()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the cached application engine, failing clearly if configuration is absent."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Copy .env.example to .env and set "
            "your PostgreSQL connection details."
        )
    return create_engine(database_url, pool_pre_ping=True, future=True)


def query_df(query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Execute a parameterized read query and return its rows as a DataFrame."""
    with get_engine().connect() as connection:
        return pd.read_sql_query(text(query), connection, params=params or {})


@contextmanager
def transaction() -> Iterator[Connection]:
    """Yield a connection with an atomic transaction."""
    with get_engine().begin() as connection:
        yield connection


def execute(query: str, params: dict[str, Any] | None = None) -> int:
    """Execute a parameterized write query and return the affected-row count."""
    with transaction() as connection:
        result = connection.execute(text(query), params or {})
        return result.rowcount


def health_check() -> bool:
    """Verify that the configured database accepts a simple query."""
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    logger.info("PostgreSQL connectivity check succeeded")
    return True
