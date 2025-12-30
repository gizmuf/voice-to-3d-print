from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from config import settings


def _load_library(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _filter_local(query: str) -> List[Dict[str, Any]]:
    data = _load_library(settings.model_library_path)
    if not query:
        return data

    query_lower = query.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", query_lower) if len(token) >= 2]
    results = []
    for item in data:
        title = str(item.get("title", "")).lower()
        tags = [str(tag).lower() for tag in item.get("tags", [])]
        if query_lower in title or any(query_lower in tag for tag in tags):
            results.append(item)
            continue
        if tokens and (any(token in title for token in tokens) or any(
            token in tag for token in tokens for tag in tags
        )):
            results.append(item)
    return results


def _extract_download_url(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("glb", "gltf", "model"):
        value = payload.get(key)
        if isinstance(value, dict):
            url = value.get("url")
            if isinstance(url, str) and url.split("?")[0].endswith(".glb"):
                return url
    url = payload.get("url")
    if isinstance(url, str) and url.split("?")[0].endswith(".glb"):
        return url
    return None


async def _fetch_sketchfab_download_url(client: httpx.AsyncClient, uid: str) -> Optional[str]:
    url = f"{settings.sketchfab_base_url}/models/{uid}/download"
    headers = {"Authorization": f"Token {settings.sketchfab_api_token}"}
    for attempt in range(3):
        response = await client.get(url, headers=headers)
        if response.status_code == 429:
            await asyncio.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code != 200:
            return None
        payload = response.json()
        return _extract_download_url(payload)
    return None


async def _search_sketchfab(query: str) -> List[Dict[str, Any]]:
    if not settings.sketchfab_api_token:
        raise ValueError("SKETCHFAB_API_TOKEN is not set")

    url = f"{settings.sketchfab_base_url}/search"
    params = {
        "type": "models",
        "q": query,
        "downloadable": "true",
        "count": 8,
    }
    headers = {"Authorization": f"Token {settings.sketchfab_api_token}"}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()

        results = payload.get("results", [])
        items: List[Dict[str, Any]] = []
        for result in results:
            uid = result.get("uid") or result.get("id")
            if not uid:
                continue
            items.append(
                {
                    "id": uid,
                    "title": result.get("name") or "Sketchfab model",
                    "tags": [tag.get("name") for tag in result.get("tags", []) if isinstance(tag, dict)],
                    "source": "sketchfab",
                }
            )
        return items


async def search_library(query: str, provider: str = "local") -> List[Dict[str, Any]]:
    provider = (provider or "local").lower()
    if provider == "local":
        return _filter_local(query)
    if provider == "sketchfab":
        return await _search_sketchfab(query)
    raise ValueError(f"Unsupported library provider: {provider}")


async def resolve_library_item(uid: str, provider: str = "local") -> Optional[str]:
    provider = (provider or "local").lower()
    if provider == "local":
        for item in _load_library(settings.model_library_path):
            if item.get("id") == uid:
                return item.get("glb_url")
        return None
    if provider == "sketchfab":
        if not settings.sketchfab_api_token:
            raise ValueError("SKETCHFAB_API_TOKEN is not set")
        async with httpx.AsyncClient(timeout=30) as client:
            return await _fetch_sketchfab_download_url(client, uid)
    raise ValueError(f"Unsupported library provider: {provider}")
