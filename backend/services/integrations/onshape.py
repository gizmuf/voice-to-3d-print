"""Small Onshape bridge for importing cloud CAD as STEP.

The first product workflow is intentionally conservative:

1. Authenticate server-side with either Onshape API keys or an OAuth bearer token.
2. Export a Part Studio / Assembly as STEP through Onshape's REST API.
3. Feed the STEP bytes into Pulsai's existing imported-STEP design path.

We do not try to edit native Onshape feature history yet. That keeps the core
Pulsai flow independent of a CAD account while giving users a much better
handoff format than STL triangles.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from config import settings


ElementKind = Literal["partstudio", "assembly"]


class OnshapeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OnshapeLocation:
    document_id: str
    wvm: Literal["w", "v", "m"]
    wvm_id: str
    element_id: str | None = None


@dataclass(frozen=True)
class OnshapeAuth:
    mode: Literal["api_key", "oauth"]
    access_token: str | None = None


def integration_status() -> dict[str, Any]:
    api_key_ready = bool(settings.onshape_access_key and settings.onshape_secret_key)
    oauth_ready = bool(
        settings.onshape_oauth_client_id
        and settings.onshape_oauth_client_secret
        and settings.onshape_oauth_redirect_uri
    )
    return {
        "configured": api_key_ready or oauth_ready,
        "api_key_configured": api_key_ready,
        "oauth_configured": oauth_ready,
        "base_url": settings.onshape_base_url,
        "mode": "api_key" if api_key_ready else "oauth" if oauth_ready else "not_configured",
    }


def make_oauth_authorization_url(*, return_to: str | None = None) -> dict[str, str]:
    if not (
        settings.onshape_oauth_client_id
        and settings.onshape_oauth_client_secret
        and settings.onshape_oauth_redirect_uri
    ):
        raise OnshapeError("Onshape OAuth is not configured.")
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": settings.onshape_oauth_client_id,
        "redirect_uri": settings.onshape_oauth_redirect_uri,
        "state": state,
    }
    if return_to:
        # The callback endpoint can use this after exchanging the code. We keep
        # it outside the OAuth state verifier because the app has no accounts yet.
        params["return_to"] = return_to
    return {
        "authorization_url": f"{settings.onshape_oauth_authorize_url}?{urlencode(params)}",
        "state": state,
    }


async def exchange_oauth_code(code: str, *, redirect_uri: str | None = None) -> dict[str, Any]:
    if not (
        settings.onshape_oauth_client_id
        and settings.onshape_oauth_client_secret
        and (redirect_uri or settings.onshape_oauth_redirect_uri)
    ):
        raise OnshapeError("Onshape OAuth is not configured.")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.onshape_oauth_client_id,
        "client_secret": settings.onshape_oauth_client_secret,
        "redirect_uri": redirect_uri or settings.onshape_oauth_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.onshape_oauth_token_url,
            data=data,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    if response.status_code >= 400:
        raise OnshapeError(f"Onshape OAuth exchange failed: {response.status_code} {response.text[:300]}")
    return response.json()


def parse_onshape_url(value: str) -> OnshapeLocation:
    """Extract d/w/e ids from a normal Onshape document URL."""
    parsed = urlparse(value.strip())
    parts = [p for p in parsed.path.split("/") if p]
    found: dict[str, str] = {}
    for idx, part in enumerate(parts):
        if part in {"d", "w", "v", "m", "e"} and idx + 1 < len(parts):
            found[part] = parts[idx + 1]
    query = parse_qs(parsed.query)
    if "d" not in found:
        raise OnshapeError("Paste an Onshape URL containing /documents/d/{documentId}/...")
    wvm = "w"
    wvm_id = found.get("w")
    if "v" in found:
        wvm = "v"
        wvm_id = found["v"]
    if "m" in found:
        wvm = "m"
        wvm_id = found["m"]
    if not wvm_id:
        # Some copied URLs keep workspace in query params.
        wvm_id = (query.get("workspaceId") or query.get("wid") or [""])[0]
    if not wvm_id:
        raise OnshapeError("Onshape URL must include a workspace, version, or microversion id.")
    return OnshapeLocation(
        document_id=found["d"],
        wvm=wvm,  # type: ignore[arg-type]
        wvm_id=wvm_id,
        element_id=found.get("e") or (query.get("elementId") or query.get("eid") or [None])[0],
    )


class OnshapeClient:
    def __init__(self, auth: OnshapeAuth | None = None) -> None:
        self.auth = auth or default_auth()
        self.base_url = settings.onshape_base_url.rstrip("/")

    async def list_documents(self, *, q: str = "", limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "GET",
            "/api/v10/documents",
            params={
                "q": q,
                "ownerType": 1,
                "sortColumn": "modifiedAt",
                "sortOrder": "desc",
                "offset": offset,
                "limit": max(1, min(limit, 50)),
            },
        )
        if isinstance(payload, dict):
            return payload.get("items") or payload.get("documents") or []
        return payload if isinstance(payload, list) else []

    async def list_elements(self, location: OnshapeLocation) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "GET",
            f"/api/v10/documents/d/{location.document_id}/{location.wvm}/{location.wvm_id}/elements",
        )
        return payload if isinstance(payload, list) else payload.get("items", [])

    async def export_step(
        self,
        location: OnshapeLocation,
        *,
        element_kind: ElementKind = "partstudio",
        timeout_s: int = 120,
    ) -> tuple[bytes, str]:
        if not location.element_id:
            raise OnshapeError("Onshape element id is required for STEP export.")
        api_kind = "assemblies" if element_kind == "assembly" else "partstudios"
        translation = await self._request_json(
            "POST",
            f"/api/v11/{api_kind}/d/{location.document_id}/{location.wvm}/{location.wvm_id}/e/{location.element_id}/export/step",
            json={
                "formatName": "STEP",
                "storeInDocument": True,
            },
        )
        translation = await self._poll_translation(translation, timeout_s=timeout_s)
        result_ids = translation.get("resultElementIds") or []
        if not result_ids:
            reason = translation.get("failureReason") or "No STEP blob id returned by Onshape."
            raise OnshapeError(str(reason))
        blob_id = result_ids[0]
        content = await self._request_bytes(
            "GET",
            f"/api/v6/blobelements/d/{location.document_id}/{location.wvm}/{location.wvm_id}/e/{blob_id}",
        )
        filename = f"onshape-{location.document_id[:8]}-{location.element_id[:8]}.step"
        return content, filename

    async def _poll_translation(self, initial: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
        state = initial.get("requestState")
        if state == "DONE":
            return initial
        href = initial.get("href")
        translation_id = initial.get("id")
        if not href and translation_id:
            href = f"{self.base_url}/api/v10/translations/{translation_id}"
        if not href:
            raise OnshapeError("Onshape export did not return a translation status URL.")

        deadline = time.monotonic() + timeout_s
        last = initial
        while time.monotonic() < deadline:
            await _sleep(1.0)
            last = await self._request_json_url("GET", href)
            state = last.get("requestState")
            if state == "DONE":
                return last
            if state in {"FAILED", "CANCELLED"}:
                raise OnshapeError(str(last.get("failureReason") or f"Onshape export {state.lower()}"))
        raise OnshapeError("Timed out waiting for Onshape STEP export.")

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        return await self._request_json_url(method, f"{self.base_url}{path}", **kwargs)

    async def _request_json_url(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self._request(method, url, **kwargs)
        if response.status_code >= 400:
            raise OnshapeError(f"Onshape API error {response.status_code}: {response.text[:300]}")
        return response.json()

    async def _request_bytes(self, method: str, path: str, **kwargs: Any) -> bytes:
        response = await self._request(
            method,
            f"{self.base_url}{path}",
            accept="application/octet-stream",
            **kwargs,
        )
        if response.status_code >= 400:
            raise OnshapeError(f"Onshape API error {response.status_code}: {response.text[:300]}")
        return response.content

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = {
            "Accept": kwargs.pop("accept", "application/json;charset=UTF-8; qs=0.09"),
            **kwargs.pop("headers", {}),
        }
        auth = None
        if self.auth.mode == "oauth":
            if not self.auth.access_token:
                raise OnshapeError("Missing Onshape OAuth access token.")
            headers["Authorization"] = f"Bearer {self.auth.access_token}"
        else:
            auth = (settings.onshape_access_key, settings.onshape_secret_key)
        async with httpx.AsyncClient(timeout=60) as client:
            return await client.request(method, url, headers=headers, auth=auth, **kwargs)


def default_auth() -> OnshapeAuth:
    if settings.onshape_access_key and settings.onshape_secret_key:
        return OnshapeAuth(mode="api_key")
    raise OnshapeError("Onshape is not configured. Set ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY, or complete OAuth.")


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
