"""Safely persist provider-generated GLB files as owned application artifacts."""

from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import httpx


def _public_https_target(url: str) -> tuple[SplitResult, str]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Provider returned an invalid model URL.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Provider model host could not be resolved.") from exc
    if not addresses:
        raise ValueError("Provider model host could not be resolved.")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Provider model URL resolved to a non-public address.")
    return parsed, str(ipaddress.ip_address(addresses[0][4][0]))


def _validate_public_https_url(url: str) -> None:
    _public_https_target(url)


def _pinned_request_target(parsed: SplitResult, address: str) -> tuple[str, str]:
    port = parsed.port or 443
    ip_host = f"[{address}]" if ":" in address else address
    netloc = ip_host if port == 443 else f"{ip_host}:{port}"
    host_header = parsed.hostname or ""
    if port != 443:
        host_header = f"{host_header}:{port}"
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, "")), host_header


async def download_generated_glb(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    max_redirects: int = 3,
) -> Path:
    """Download a provider-returned GLB with SSRF and size protections.

    The URL is not supplied directly by a caller: it comes from an authenticated
    Meshy/Tripo response. Every redirect is still revalidated and only a binary
    GLB payload is accepted before it becomes an owned local/GCS artifact.
    """

    current = url
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=120, follow_redirects=False, trust_env=False) as client:
        for redirect_count in range(max_redirects + 1):
            parsed, address = _public_https_target(current)
            pinned_url, host_header = _pinned_request_target(parsed, address)
            async with client.stream(
                "GET",
                pinned_url,
                headers={"host": host_header},
                extensions={"sni_hostname": parsed.hostname},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect_count >= max_redirects:
                        raise ValueError("Provider model URL redirected too many times.")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Provider model redirect was invalid.")
                    current = urljoin(current, location)
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise ValueError(
                        f"Provider model download failed with HTTP {response.status_code}."
                    ) from exc
                expected = response.headers.get("content-length")
                if expected:
                    try:
                        expected_bytes = int(expected)
                    except ValueError as exc:
                        raise ValueError("Provider model returned an invalid size.") from exc
                    if expected_bytes > max_bytes:
                        raise ValueError("Provider model exceeds the configured size limit.")
                total = 0
                prefix = bytearray()
                with destination.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            output.close()
                            destination.unlink(missing_ok=True)
                            raise ValueError("Provider model exceeds the configured size limit.")
                        if len(prefix) < 4:
                            prefix.extend(chunk[: 4 - len(prefix)])
                        output.write(chunk)
                if total < 12 or bytes(prefix) != b"glTF":
                    destination.unlink(missing_ok=True)
                    raise ValueError("Provider response was not a binary GLB model.")
                return destination
    raise ValueError("Provider model download failed.")


__all__ = ["download_generated_glb"]
