import pytest



async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}



async def test_health_no_auth_required(unauthed_client):
    """Health endpoint should be public — no API key needed."""
    resp = await unauthed_client.get("/health")
    assert resp.status_code == 200
