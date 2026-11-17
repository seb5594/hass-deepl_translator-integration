"""What the services need from a connection to DeepL, whichever way the user signed in."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .api import (
    Capabilities,
    Language,
    TranslateOptions,
    TranslatedDocument,
    Translation,
    Usage,
)

__all__ = ["Capabilities", "TranslationBackend"]


class TranslationBackend(Protocol):
    """The API-key client and the OAuth (MCP) client both look like this."""

    capabilities: Capabilities

    async def async_translate(
        self, texts: Sequence[str], options: TranslateOptions
    ) -> list[Translation]:
        """Translate texts in order."""

    async def async_get_usage(self) -> Usage:
        """The character quota (only if ``capabilities.usage``)."""

    async def async_get_languages(self, language_type: str = "target") -> list[Language]:
        """The supported languages (only if ``capabilities.languages``)."""

    async def async_translate_document(
        self, content: bytes, filename: str, options: TranslateOptions, timeout: float
    ) -> TranslatedDocument:
        """Translate a file (only if ``capabilities.documents``)."""
