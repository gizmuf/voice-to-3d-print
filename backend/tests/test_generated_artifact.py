from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import pytest
import httpx

import app as app_module
from services import generated_artifact


def test_generated_artifact_rejects_http_and_private_addresses(monkeypatch) -> None:
    with pytest.raises(ValueError, match="invalid model URL"):
        generated_artifact._validate_public_https_url("http://example.com/model.glb")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))],
    )
    with pytest.raises(ValueError, match="non-public"):
        generated_artifact._validate_public_https_url("https://provider.example/model.glb")


def test_generated_artifact_accepts_public_https_address(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    generated_artifact._validate_public_https_url("https://provider.example/model.glb")


def test_provider_error_copy_does_not_expose_signed_url() -> None:
    request = httpx.Request("GET", "https://provider.example/model.glb?secret=signed-token")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("failed", request=request, response=response)

    detail = app_module._safe_provider_failure(error)

    assert detail == "Provider returned HTTP 503."
    assert "signed-token" not in detail


def test_generated_glb_is_downloaded_only_after_validation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    real_client = httpx.AsyncClient
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "provider.example"
        assert request.extensions["sni_hostname"] == "provider.example"
        return httpx.Response(
            200,
            headers={"content-length": "12"},
            content=b"glTF" + b"\x00" * 8,
        )

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(
        generated_artifact.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )
    destination = tmp_path / "provider.glb"

    result = asyncio.run(
        generated_artifact.download_generated_glb(
            "https://provider.example/model.glb",
            destination,
            max_bytes=1024,
        )
    )

    assert result == destination
    assert destination.read_bytes().startswith(b"glTF")
