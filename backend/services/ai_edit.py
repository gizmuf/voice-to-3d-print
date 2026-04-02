from __future__ import annotations

import json

import httpx
from fastapi import HTTPException

from config import settings
from services.editable_model import BodyNode, EditableModel


def _find_body(bodies: list[BodyNode], body_id: str, parent: BodyNode | None = None) -> tuple[BodyNode | None, BodyNode | None]:
    for body in bodies:
        if body.id == body_id:
            return body, parent
        found, found_parent = _find_body(body.children, body_id, body)
        if found:
            return found, found_parent
    return None, None


async def ai_edit_workspace_model(model: EditableModel, body_id: str, prompt: str) -> dict[str, float | str | bool]:
    if not model.bodies:
        raise HTTPException(status_code=400, detail="Workspace has no editable root body.")

    body, parent = _find_body(model.bodies, body_id)
    if not body:
        raise HTTPException(status_code=404, detail="Selected feature was not found.")

    root = model.bodies[0]
    if str(root.params.get("_template_id", "")) != "perforated_disc":
        raise HTTPException(status_code=400, detail="AI edit is currently limited to native perforated-disc workspaces.")

    siblings = [candidate for candidate in (parent.children if parent else model.bodies) if candidate.id != body.id]
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "You are a CAD parameter editor. "
                            "Return ONLY JSON. "
                            "Allowed response shapes are "
                            '{"param_changes": {"existing_param_name": new_value}} '
                            'or {"error": "reason"}. '
                            "Only change params that already exist on the selected feature. "
                            "If the instruction is ambiguous, unsupported, or requires guessing, return error.\n\n"
                            f"Feature kind: {body.kind}\n"
                            f"Feature label: {body.label}\n"
                            f"Current params: {json.dumps(body.params)}\n"
                            f"Parent params: {json.dumps(parent.params if parent else {})}\n"
                            f"Siblings: {json.dumps([{sibling.label: sibling.params} for sibling in siblings])}\n"
                            f"Instruction: {prompt}\n"
                        )
                    }
                ],
            }
        ],
        "modelName": settings.gemini_model,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(settings.gemini_proxy_url, json=payload)
        response.raise_for_status()
        data = response.json()

    text = data.get("text") if isinstance(data, dict) else None
    if not text:
        raise HTTPException(status_code=502, detail="AI edit did not return a usable response.")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail="AI edit returned invalid JSON.") from exc

    if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
        raise HTTPException(status_code=422, detail=parsed["error"])

    if not isinstance(parsed, dict) or not isinstance(parsed.get("param_changes"), dict):
        raise HTTPException(status_code=502, detail="AI edit returned an unsupported response shape.")

    param_changes = parsed["param_changes"]
    invalid_keys = [key for key in param_changes.keys() if key not in body.params]
    if invalid_keys:
        raise HTTPException(status_code=422, detail=f"AI edit referenced unsupported params: {', '.join(invalid_keys)}")

    return param_changes
