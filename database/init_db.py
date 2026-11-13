"""Create the configured database if needed and install the non-destructive schema."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = Path(__file__).with_name("schema.sql")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def create_database_if_missing(database_url: str) -> None:
    """Create the target database only when it does not already exist."""
    url = make_url(database_url)
    if not url.database:
        raise ValueError("DATABASE_URL must include a target database name.")
    maintenance_url = url.set(
        drivername="postgresql", database="postgres"
    ).render_as_string(hide_password=False)
    with psycopg.connect(maintenance_url, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)
        ).fetchone()
        if exists:
            logger.info("Database %s already exists; leaving it intact.", url.database)
            return
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(url.database))
        )
        logger.info("Created database %s.", url.database)


def initialize_schema(database_url: str) -> None:
    """Apply CREATE TABLE/INDEX IF NOT EXISTS statements without dropping data."""
    statements = [
        statement.strip()
        for statement in SCHEMA_FILE.read_text(encoding="utf-8").split(";")
        if statement.strip()
    ]
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()
    logger.info("Schema is ready; no existing tables or rows were dropped.")


def main() -> None:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-create-database",
        action="store_true",
        help="Do not create the configured database when it is missing.",
    )
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is missing. Configure it in the project .env file.")
    if not args.no_create_database:
        create_database_if_missing(database_url)
    initialize_schema(database_url)


if __name__ == "__main__":
    main()
