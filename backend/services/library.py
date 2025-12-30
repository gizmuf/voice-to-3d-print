from __future__ import annotations

import asyncio
import json
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
    results = []
    for item in data:
        title = str(item.get("title", "")).lower()
        tags = [str(tag).lower() for tag in item.get("tags", [])]
        if query_lower in title or any(query_lower in tag for tag in tags):
            results.append(item)
    return results


def _extract_download_url(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("glb", "gltf", "model"):
        value = payload.get(key)
        if isinstance(value, dict):
            url = value.get("url")
            if isinstance(url, str) and url.endswith(".glb"):
                return url
    url = payload.get("url")
    if isinstance(url, str) and url.endswith(".glb"):
        return url
    return None


async def _fetch_sketchfab_download_url(client: httpx.AsyncClient, uid: str) -> Optional[str]:
    url = f"{settings.sketchfab_base_url}/models/{uid}/download"
    headers = {"Authorization": f"Token {settings.sketchfab_api_token}"}
    response = await client.get(url, headers=headers)
    if response.status_code != 200:
        return None
    payload = response.json()
    return _extract_download_url(payload)


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
        tasks = []
        items: List[Dict[str, Any]] = []
        for result in results:
            uid = result.get("uid") or result.get("id")
            if not uid:
                continue
            tasks.append(_fetch_sketchfab_download_url(client, uid))
            items.append(
                {
                    "id": uid,
                    "title": result.get("name") or "Sketchfab model",
                    "tags": [tag.get("name") for tag in result.get("tags", []) if isinstance(tag, dict)],
                    "source": "sketchfab",
                }
            )

        download_urls = await asyncio.gather(*tasks, return_exceptions=True)
        filtered = []
        for item, url in zip(items, download_urls):
            if isinstance(url, Exception) or not url:
                continue
            item["glb_url"] = url
            filtered.append(item)
        return filtered


async def search_library(query: str, provider: str = "local") -> List[Dict[str, Any]]:
    provider = (provider or "local").lower()
    if provider == "local":
        return _filter_local(query)
    if provider == "sketchfab":
        return await _search_sketchfab(query)
    raise ValueError(f"Unsupported library provider: {provider}")
