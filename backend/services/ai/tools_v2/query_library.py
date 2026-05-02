"""Tool: search the snippet library."""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.ai.tools_v2 import DesignContext
from services.codegen.library import search


class QueryLibraryInput(BaseModel):
    intent: str = Field(
        description="Natural-language intent — what kind of feature are you trying to add?"
    )
    process: str | None = Field(
        default=None,
        description="Optional filter: 'fdm' or 'cnc'. Omit to include all.",
    )
    limit: int = Field(default=5, ge=1, le=10)


TOOL_DEFINITION = {
    "name": "query_library",
    "description": (
        "Search the build123d snippet library for idioms that match an intent "
        "(e.g. 'triangular holes around a circle', 'shell with open top', "
        "'counterbore for an M3 screw'). Returns up to `limit` snippets with "
        "their code blocks. Use the result with replace_feature/append_feature."
    ),
    "input_schema": QueryLibraryInput.model_json_schema(),
}


def execute(payload: dict, ctx: DesignContext) -> dict:
    try:
        params = QueryLibraryInput.model_validate(payload)
    except Exception as exc:
        return {"error": f"Invalid input: {exc}"}
    snippets = search(params.intent, process=params.process, limit=params.limit)
    return {
        "ok": True,
        "matches": [
            {
                "name": s.name,
                "intent": s.intent,
                "process": list(s.process),
                "code": s.code,
                "notes": s.notes,
            }
            for s in snippets
        ],
        "match_count": len(snippets),
    }


__all__ = ["TOOL_DEFINITION", "QueryLibraryInput", "execute"]
