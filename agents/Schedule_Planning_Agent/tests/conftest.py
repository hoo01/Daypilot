import pytest
import httpx
from app.main import app


@pytest.fixture
async def http_client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
