from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from config import settings


def _load_library(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def search_library(query: str) -> List[Dict[str, Any]]:
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
