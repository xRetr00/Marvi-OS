import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.app import create_app


@pytest.mark.asyncio
async def test_health_exposes_branding_version_and_component_readiness() -> None:
    transport = ASGITransport(app=create_app(version="0.1.0-test"))
    async with AsyncClient(transport=transport, base_url="http://marvi.local") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["product"] == "Marvi OS"
    assert payload["version"] == "0.1.0-test"
    assert payload["components"]["gateway"]["state"] == "ready"
    assert payload["components"]["livekit"]["state"] == "pending"
    assert payload["components"]["voice"]["state"] == "pending"
