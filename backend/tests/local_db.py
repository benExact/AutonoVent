"""Helpers for tests that must stay on the local PostgreSQL server."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

from app.core.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def local_database_url():
    get_settings.cache_clear()
    url = make_url(get_settings().database_url)
    if url.host not in {"127.0.0.1", "localhost"}:
        pytest.fail("Database tests only run against PostgreSQL on this machine.")
    if not url.database:
        pytest.fail("DATABASE_URL has no database name.")
    return url


def ensure_isolated_database() -> str:
    url = local_database_url()
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = 'autonovent_test'")
        ).scalar()
        if not exists:
            connection.execute(text("CREATE DATABASE autonovent_test"))
    admin.dispose()

    test_url = url.set(database="autonovent_test").render_as_string(hide_password=False)
    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
    )
    return test_url
