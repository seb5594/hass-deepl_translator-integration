"""Translate through DeepL's hosted MCP server, for accounts that signed in with OAuth.

The server is spoken to over Streamable HTTP (JSON-RPC in POST requests). Only text
translation is available this way: the MCP server offers no usage figures, no language
list endpoint and no document upload that Home Assistant could use, and it cannot protect
placeholders with XML tags. The capabilities say so, and the services refuse the rest
before anything is sent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
import logging
from typing import Any

import aiohttp

from . import protocol
from .api import (
    Capabilities,
    DeepLAuthError,
    DeepLConnectionError,
    DeepLError,
    DeepLQuotaError,
    DeepLRequestError,
    Language,
    TranslateOptions,
    TranslatedDocument,
    Translation,
    Usage,
)
from .const import MCP_URL, REQUEST_TIMEOUT

_LOGGER = logging.getLogger(__name__)

TokenGetter = Callable[[], Awaitable[str]]


class DeepLMcpBackend:
    """Text translation through the ``translate-text`` tool of the hosted MCP server."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        get_token: TokenGetter,
        user_agent: str,
        url: str = MCP_URL,
    ) -> None:
        self._session = session
        self._get_token = get_token
        self._user_agent = user_agent
        self._url = url
        self._session_id: str | None = None
        self._initialized = False
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._arguments: dict[str, tuple[str, bool]] = {}
        self.capabilities = Capabilities(
            documents=False,
            usage=False,
            languages=False,
            tag_handling=False,
            max_text_bytes=None,
            max_request_characters=protocol.FREE_PLAN_REQUEST_CHARACTERS,
        )

    async def async_connect(self) -> None:
        """Shake hands, find the translation tool and learn how to call it."""
        async with self._lock:
            await self._initialize()
            tools = (await self._rpc("tools/list")).get("tools", [])
        by_name = {tool.get("name"): tool for tool in tools if isinstance(tool, dict)}
        tool = by_name.get(protocol.TRANSLATE_TOOL)
        if tool is None:
            raise DeepLError("DeepL's MCP server offers no text translation for this account")
        self._arguments = protocol.resolve_arguments(tool.get("inputSchema") or {})
        if "text" not in self._arguments or "target" not in self._arguments:
            raise DeepLError("DeepL's MCP translation tool takes arguments this integration does not know")
        self.capabilities = Capabilities(
            documents=False,
            usage=False,
            languages=False,
            tag_handling=False,
            max_text_bytes=None,
            max_request_characters=protocol.infer_request_characters(list(by_name)),
        )

    async def async_translate(
        self, texts: Sequence[str], options: TranslateOptions
    ) -> list[Translation]:
        """Translate texts in order, in as few tool calls as the limits allow."""
        takes_list = self._arguments["text"][1]
        groups = protocol.split_by_characters(
            texts,
            self.capabilities.max_request_characters or protocol.FREE_PLAN_REQUEST_CHARACTERS,
            protocol.MAX_TEXTS_PER_CALL if takes_list else 1,
        )
        results: list[Translation] = []
        for group in groups:
            arguments = protocol.build_arguments(
                self._arguments,
                group,
                options.target_lang,
                source=options.source_lang,
                formality=options.formality if options.formality != "default" else None,
                context=options.context,
                glossary_id=options.glossary_id,
            )
            result = await self._call_tool(protocol.TRANSLATE_TOOL, arguments)
            try:
                items = protocol.extract_translations(result)
            except ValueError as err:
                raise _tool_error(str(err)) from err
            if len(items) != len(group):
                raise DeepLError("DeepL's MCP server returned an unexpected number of translations")
            results.extend(Translation(text, detected) for text, detected in items)
        return results

    async def async_get_usage(self) -> Usage:
        """Not offered through MCP."""
        raise DeepLRequestError("Usage figures need an account that signed in with an API key")

    async def async_get_languages(self, language_type: str = "target") -> list[Language]:
        """Not offered through MCP."""
        raise DeepLRequestError("The language list needs an account that signed in with an API key")

    async def async_translate_document(
        self, content: bytes, filename: str, options: TranslateOptions, timeout: float
    ) -> TranslatedDocument:
        """Not offered through MCP."""
        raise DeepLRequestError("Document translation needs an account that signed in with an API key")

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            if not self._initialized:
                await self._initialize()
            try:
                return await self._rpc("tools/call", {"name": name, "arguments": arguments})
            except _SessionExpired:
                await self._initialize()
                return await self._rpc("tools/call", {"name": name, "arguments": arguments})

    async def _initialize(self) -> None:
        self._session_id = None
        self._initialized = False
        await self._rpc(
            "initialize",
            {
                "protocolVersion": protocol.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "home-assistant-deepl-translator", "version": "1"},
            },
        )
        self._initialized = True
        await self._notify("notifications/initialized")

    async def _notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method}, expect_answer=False)

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._request_id += 1
        message = protocol.rpc_request(self._request_id, method, params)
        answer = await self._post(message, expect_answer=True)
        if "error" in answer:
            raise _tool_error(str(answer["error"].get("message", answer["error"])))
        return answer.get("result", {})

    async def _post(self, message: dict[str, Any], expect_answer: bool) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {await self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": self._user_agent,
        }
        if self._initialized or message.get("method") != "initialize":
            headers["MCP-Protocol-Version"] = protocol.PROTOCOL_VERSION
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            async with self._session.post(
                self._url,
                json=message,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status in (401, 403):
                    raise DeepLAuthError("DeepL rejected the sign-in")
                if response.status == 404 and self._session_id:
                    raise _SessionExpired
                if response.status >= 400:
                    raise _http_error(response.status, await response.text())
                if session_id := response.headers.get("Mcp-Session-Id"):
                    self._session_id = session_id
                if not expect_answer:
                    return {}
                body = await response.text()
                try:
                    return protocol.parse_response_body(
                        body, response.headers.get("Content-Type", ""), message["id"]
                    )
                except ValueError as err:
                    raise DeepLError(f"DeepL's MCP server answered unexpectedly: {err}") from err
        except asyncio.TimeoutError as err:
            raise DeepLConnectionError("Timed out while talking to DeepL") from err
        except aiohttp.ClientError as err:
            raise DeepLConnectionError(f"Cannot reach DeepL: {err}") from err


class _SessionExpired(Exception):
    """The server forgot the MCP session; start a new one."""


def _http_error(status: int, body: str) -> DeepLError:
    return _tool_error(f"HTTP {status}: {body[:200]}" if body else f"HTTP {status}", status)


def _tool_error(message: str, status: int | None = None) -> DeepLError:
    """Sort an error message into the exceptions the services know."""
    lowered = message.lower()
    if status == 456 or "quota" in lowered:
        return DeepLQuotaError(message)
    if status is not None and status >= 500:
        return DeepLError(message)
    return DeepLRequestError(message)
