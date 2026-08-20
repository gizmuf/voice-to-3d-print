"""Production ASGI entrypoint with fail-closed configuration validation."""

from __future__ import annotations

import os

from config import settings
from services.runtime_validation import validate_production_settings


validate_production_settings(settings, os.environ)

# Import only after validation so an unsafe deployment never initializes the
# API, provider clients, artifact directories, or a healthy endpoint.
from app import app  # noqa: E402


__all__ = ["app"]
