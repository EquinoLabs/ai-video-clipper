"""Pytest configuration and shared test fixtures."""

import os
import pytest
from httpx import ASGITransport, AsyncClient

# Set testing environment before loading application
os.environ["ENVIRONMENT"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"

from app.main import create_app


@pytest.fixture
def app():
    """Create a new FastAPI instance for tests."""
    return create_app()


@pytest.fixture
async def client(app):
    """Async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
