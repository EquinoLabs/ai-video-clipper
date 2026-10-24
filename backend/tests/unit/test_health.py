"""Unit tests for the health check endpoint."""

import pytest


@pytest.mark.asyncio
async def test_health_endpoint_success(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["environment"] == "test"
    assert "version" in data
    assert "timestamp" in data
    assert "ffmpeg_available" in data
    assert "subsystems" in data

    subsystems = data["subsystems"]
    assert "media_engine" in subsystems
    assert "database" in subsystems
    assert "object_storage" in subsystems
    assert "transcription" in subsystems
    assert "llm" in subsystems


@pytest.mark.asyncio
async def test_root_index_endpoint(client):
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "AI Video Clipper"
    assert data["health_url"] == "/api/v1/health"
