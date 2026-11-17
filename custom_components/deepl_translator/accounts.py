"""Identity helpers for API-key accounts, shared by the config flow and the YAML import."""

from __future__ import annotations

import hashlib

from .const import FREE_KEY_SUFFIX


def account_unique_id(api_key: str) -> str:
    """Identify an account without keeping the key itself in the registry."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def account_title(api_key: str) -> str:
    """The name shown in the UI: free and Pro keys are told apart by their suffix."""
    return "DeepL (Free)" if api_key.endswith(FREE_KEY_SUFFIX) else "DeepL (Pro)"
