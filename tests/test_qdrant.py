import asyncio

import httpx
import pytest
from fastapi import HTTPException

from schemas import Environment
from services.qdrant_service import collection_count


@pytest.mark.parametrize("size", [0, 2])
def test_collection_count(monkeypatch, size):
    monkeypatch.setenv("QDRANT_URL_DEV", "https://qdrant.test")
    monkeypatch.setenv("QDRANT_API_KEY_DEV", "test-key")
    def read(request):
        assert str(request.url) == "https://qdrant.test/collections"
        assert request.headers["api-key"] == "test-key"
        return httpx.Response(200, json={"result": {"collections": [{"name": str(i)} for i in range(size)]}})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(read), **kw))
    assert asyncio.run(collection_count(Environment.DEV)) == size


def test_missing_dev_does_not_read_production(monkeypatch):
    monkeypatch.delenv("QDRANT_URL_DEV", raising=False)
    monkeypatch.setenv("QDRANT_URL", "https://prod.test")
    with pytest.raises(HTTPException) as error:
        asyncio.run(collection_count(Environment.DEV))
    assert error.value.status_code == 503
