"""A lean asynchronous client for the DeepL REST API.

It only needs the aiohttp session Home Assistant already shares, so the integration
brings no extra dependency and no extra process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import logging
from time import monotonic
from typing import Any

import aiohttp

from .const import (
    API_URL_FREE,
    API_URL_PRO,
    DOCUMENT_POLL_MAX_DELAY,
    DOCUMENT_POLL_MIN_DELAY,
    FREE_KEY_SUFFIX,
    LANGUAGES_CACHE_SECONDS,
    MAX_ATTEMPTS,
    MAX_REQUEST_BYTES,
    MAX_RETRY_DELAY,
    MAX_TEXTS_PER_REQUEST,
    REQUEST_TIMEOUT,
    UNLIMITED_CHARACTER_LIMIT,
)

_LOGGER = logging.getLogger(__name__)

RETRYABLE_STATUSES = (429, 529)


class DeepLError(Exception):
    """Base class for everything that can go wrong while talking to DeepL."""


class DeepLConnectionError(DeepLError):
    """DeepL could not be reached in time."""


class DeepLAuthError(DeepLError):
    """The API key was rejected."""


class DeepLQuotaError(DeepLError):
    """The character quota of the account is used up."""


class DeepLRequestError(DeepLError):
    """DeepL refused the request, for example because of an unsupported language."""


class DeepLDocumentError(DeepLError):
    """A document translation failed or took too long."""


@dataclass(frozen=True)
class TranslateOptions:
    """Everything that shapes a translation besides the text itself."""

    target_lang: str
    source_lang: str | None = None
    formality: str = "default"
    context: str | None = None
    glossary_id: str | None = None
    tag_handling: str = "none"
    ignore_tags: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, Any]:
        """The fields of the request body, leaving out whatever is not set."""
        payload: dict[str, Any] = {"target_lang": self.target_lang}
        if self.source_lang:
            payload["source_lang"] = self.source_lang
        if self.formality != "default":
            payload["formality"] = self.formality
        if self.context:
            payload["context"] = self.context
        if self.glossary_id:
            payload["glossary_id"] = self.glossary_id
        if self.tag_handling != "none":
            payload["tag_handling"] = self.tag_handling
        if self.ignore_tags:
            payload["ignore_tags"] = list(self.ignore_tags)
        return payload


@dataclass(frozen=True)
class Translation:
    """One translated text."""

    text: str
    detected_source_language: str | None = None


@dataclass(frozen=True)
class Usage:
    """The character quota of the account."""

    character_count: int
    character_limit: int
    end_time: str | None = None

    @property
    def is_unlimited(self) -> bool:
        """Pro accounts without a cap report a huge or empty limit."""
        return not 0 < self.character_limit < UNLIMITED_CHARACTER_LIMIT

    @property
    def characters_remaining(self) -> int | None:
        """Characters left in the current period, or None without a limit."""
        if self.is_unlimited:
            return None
        return max(self.character_limit - self.character_count, 0)

    @property
    def usage_percent(self) -> float | None:
        """Share of the quota that is used up, or None without a limit."""
        if self.is_unlimited:
            return None
        return round(self.character_count / self.character_limit * 100, 1)


@dataclass(frozen=True)
class Language:
    """A language DeepL can translate from or to."""

    code: str
    name: str
    supports_formality: bool | None = None


@dataclass(frozen=True)
class TranslatedDocument:
    """The result of a document translation."""

    document_id: str
    billed_characters: int
    content: bytes


def split_into_batches(texts: Sequence[str]) -> Iterator[list[str]]:
    """Group texts into requests that stay within DeepL's count and size limits."""
    batch: list[str] = []
    size = 0
    for text in texts:
        text_size = len(text.encode("utf-8"))
        if batch and (len(batch) >= MAX_TEXTS_PER_REQUEST or size + text_size > MAX_REQUEST_BYTES):
            yield batch
            batch, size = [], 0
        batch.append(text)
        size += text_size
    if batch:
        yield batch


class DeepLClient:
    """Talks to the Free or the Pro endpoint, depending on the API key."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str, user_agent: str) -> None:
        self._session = session
        self._api_key = api_key
        self._user_agent = user_agent
        self._languages: dict[str, tuple[float, list[Language]]] = {}

    @property
    def is_free_plan(self) -> bool:
        """Free keys end in ``:fx`` and use their own host."""
        return self._api_key.endswith(FREE_KEY_SUFFIX)

    @property
    def base_url(self) -> str:
        """The API host that belongs to the key."""
        return API_URL_FREE if self.is_free_plan else API_URL_PRO

    async def async_get_usage(self) -> Usage:
        """Read the character quota; also the cheapest way to check a key."""
        data = await self._request("GET", "/v2/usage")
        return Usage(
            character_count=int(data.get("character_count", 0)),
            character_limit=int(data.get("character_limit", 0)),
            end_time=data.get("end_time"),
        )

    async def async_translate(
        self, texts: Sequence[str], options: TranslateOptions
    ) -> list[Translation]:
        """Translate texts, keeping their order. Empty texts must be filtered by the caller."""
        results: list[Translation] = []
        for batch in split_into_batches(texts):
            body = {"text": batch, **options.as_payload()}
            data = await self._request("POST", "/v2/translate", json=body)
            translations = data.get("translations", [])
            if len(translations) != len(batch):
                raise DeepLError("DeepL returned an unexpected number of translations")
            results.extend(
                Translation(item["text"], item.get("detected_source_language"))
                for item in translations
            )
        return results

    async def async_get_languages(self, language_type: str = "target") -> list[Language]:
        """List the supported languages; the answer is kept for a day."""
        cached = self._languages.get(language_type)
        if cached and monotonic() - cached[0] < LANGUAGES_CACHE_SECONDS:
            return cached[1]
        data = await self._request("GET", "/v2/languages", params={"type": language_type})
        languages = [
            Language(item["language"], item["name"], item.get("supports_formality"))
            for item in data
        ]
        self._languages[language_type] = (monotonic(), languages)
        return languages

    async def async_translate_document(
        self,
        content: bytes,
        filename: str,
        options: TranslateOptions,
        timeout: float,
    ) -> TranslatedDocument:
        """Upload a file, wait for the translation and download the result."""
        form = aiohttp.FormData()
        for field, value in options.as_payload().items():
            if field in ("target_lang", "source_lang", "formality", "glossary_id"):
                form.add_field(field, value)
        form.add_field("file", content, filename=filename)
        upload = await self._request("POST", "/v2/document", data=form)

        document_id = upload["document_id"]
        credentials = {"document_key": upload["document_key"]}
        deadline = monotonic() + timeout
        while True:
            status = await self._request("POST", f"/v2/document/{document_id}", json=credentials)
            state = status.get("status")
            if state == "done":
                break
            if state == "error":
                raise DeepLDocumentError(status.get("error_message") or "DeepL could not translate the document")
            delay = min(
                max(status.get("seconds_remaining") or 0, DOCUMENT_POLL_MIN_DELAY),
                DOCUMENT_POLL_MAX_DELAY,
            )
            if monotonic() + delay > deadline:
                raise DeepLDocumentError(
                    f"The translation was not finished after {int(timeout)} seconds"
                )
            await asyncio.sleep(delay)

        result = await self._request(
            "POST", f"/v2/document/{document_id}/result", json=credentials, expect_json=False
        )
        return TranslatedDocument(document_id, int(status.get("billed_characters", 0)), result)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: Any = None,
        params: dict[str, str] | None = None,
        expect_json: bool = True,
    ) -> Any:
        """Send a request, retrying when DeepL asks to slow down."""
        headers = {
            "Authorization": f"DeepL-Auth-Key {self._api_key}",
            "User-Agent": self._user_agent,
        }
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with self._session.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=headers,
                    json=json,
                    data=data,
                    params=params,
                    timeout=timeout,
                ) as response:
                    if response.status in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS:
                        delay = _retry_delay(response.headers.get("Retry-After"), attempt)
                        _LOGGER.debug("DeepL asked to slow down, retrying in %s s", delay)
                    else:
                        await _raise_for_status(response)
                        return await response.json() if expect_json else await response.read()
            except asyncio.TimeoutError as err:
                raise DeepLConnectionError("Timed out while talking to DeepL") from err
            except aiohttp.ClientError as err:
                raise DeepLConnectionError(f"Cannot reach DeepL: {err}") from err
            await asyncio.sleep(delay)
        raise DeepLError("DeepL is overloaded, try again later")  # pragma: no cover


def _retry_delay(retry_after: str | None, attempt: int) -> float:
    """Honour the Retry-After header, otherwise back off 1, 2, 4 ... seconds."""
    try:
        return min(float(retry_after), MAX_RETRY_DELAY) if retry_after else 2 ** (attempt - 1)
    except ValueError:
        return 2 ** (attempt - 1)


async def _raise_for_status(response: aiohttp.ClientResponse) -> None:
    """Translate an HTTP error into the matching exception."""
    if response.status < 400:
        return
    message = await _error_message(response)
    if response.status in (401, 403):
        raise DeepLAuthError(message or "The API key was rejected")
    if response.status == 456:
        raise DeepLQuotaError(message or "The DeepL character quota is used up")
    if response.status in RETRYABLE_STATUSES:
        raise DeepLError("DeepL is overloaded or the rate limit was hit, try again later")
    if response.status < 500:
        raise DeepLRequestError(message or f"DeepL rejected the request (HTTP {response.status})")
    raise DeepLError(message or f"DeepL answered with HTTP {response.status}")


async def _error_message(response: aiohttp.ClientResponse) -> str:
    """The human readable part of an error answer."""
    try:
        payload = await response.json(content_type=None)
    except (aiohttp.ClientError, ValueError):
        return ""
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("detail") or "")[:300]
    return ""
