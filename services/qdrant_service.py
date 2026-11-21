"""Current collection count from the configured Qdrant REST endpoint."""
import os

import httpx
from fastapi import HTTPException
from schemas import Environment


async def collection_count(env: Environment) -> int:
    suffix = "" if env == Environment.PROD else "_" + env.value
    url = os.getenv("QDRANT_URL" + suffix, "").strip()
    if not url:
        raise HTTPException(503, "Qdrant não configurado neste ambiente.")
    key = os.getenv("QDRANT_API_KEY" + suffix)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url.rstrip("/") + "/collections", headers={"api-key": key} if key else {})
            if response.status_code in (401, 403):
                raise HTTPException(403, "Qdrant recusou a credencial de leitura.")
            response.raise_for_status()
            collections = response.json()["result"]["collections"]
            if not isinstance(collections, list) or not all(isinstance(item, dict) and isinstance(item.get("name"), str) for item in collections):
                raise ValueError("Invalid collections")
            return len(collections)
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "Não foi possível ler as coleções do Qdrant.") from exc
