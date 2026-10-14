"""Shared fixtures. Database tests stay on the local isolated database."""

import pytest

from tests.local_db import ensure_isolated_database


@pytest.fixture(scope="module")
def isolated_database_url() -> str:
    return ensure_isolated_database()
