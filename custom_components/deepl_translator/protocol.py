"""Protocol details of DeepL's hosted MCP server and its OAuth sign-in, as plain functions.

Nothing in here talks to the network or imports Home Assistant, so it can be tested alone.
Where DeepL's published documentation leaves a detail open (the exact argument names of the
translation tool), the code reads them from the tool's own schema instead of guessing.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
import hashlib
import json
import re
import secrets
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
TRANSLATE_TOOL = "translate-text"
GLOSSARY_TOOL = "list-glossaries"

# Published limits per translation request (characters). Free accounts see no glossary tools.
FREE_PLAN_REQUEST_CHARACTERS = 5000
SEAT_PLAN_REQUEST_CHARACTERS = 128000
MAX_TEXTS_PER_CALL = 50

# Spellings of the same argument seen across DeepL's tools, compared without case and separators.
ARGUMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "text": ("text", "texts", "input", "content"),
    "target": ("targetlangcode", "targetlang", "targetlanguage", "targetlanguages", "targetlangs", "targetlangcodes"),
    "source": ("sourcelangcode", "sourcelang", "sourcelanguage"),
    "formality": ("formality",),
    "context": ("context",),
    "glossary": ("glossaryid", "glossary"),
}

_TEXT_KEYS = ("text", "translatedText", "translated_text", "translation")
_DETECTED_KEYS = ("detected_source_language", "detectedSourceLanguage", "detectedSourceLang", "detected_source_lang")


# --- JSON-RPC over Streamable HTTP ---------------------------------------------------------------


def parse_response_body(body: str, content_type: str, request_id: int) -> dict[str, Any]:
    """Return the JSON-RPC answer to a request, whether the server sent JSON or an event stream."""
    if "text/event-stream" not in content_type:
        return _as_message(json.loads(body))
    for event in re.split(r"\r?\n\r?\n", body):
        data = "\n".join(
            line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")
        )
        if not data:
            continue
        try:
            message = json.loads(data)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    raise ValueError("The event stream held no answer to the request")


def _as_message(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("The MCP server answered with something other than a JSON object")
    return payload


def rpc_request(request_id: int, method: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A JSON-RPC request."""
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = dict(params)
    return message


# --- the translation tool ------------------------------------------------------------------------


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def resolve_arguments(input_schema: Mapping[str, Any]) -> dict[str, tuple[str, bool]]:
    """Map our argument roles to the tool's property names: ``{role: (name, takes_a_list)}``."""
    properties: Mapping[str, Any] = input_schema.get("properties") or {}
    resolved: dict[str, tuple[str, bool]] = {}
    for role, aliases in ARGUMENT_ALIASES.items():
        for name, definition in properties.items():
            if _normalize(name) in aliases:
                is_list = isinstance(definition, Mapping) and definition.get("type") == "array"
                resolved[role] = (name, is_list)
                break
    return resolved


def build_arguments(
    mapping: Mapping[str, tuple[str, bool]],
    texts: Sequence[str],
    target: str,
    *,
    source: str | None = None,
    formality: str | None = None,
    context: str | None = None,
    glossary_id: str | None = None,
) -> dict[str, Any]:
    """The ``arguments`` of one tool call; optional values the tool lacks are left out."""
    arguments: dict[str, Any] = {}

    def put(role: str, value: Any) -> None:
        if value is None or role not in mapping:
            return
        name, is_list = mapping[role]
        arguments[name] = [value] if is_list and not isinstance(value, list) else value

    put("text", list(texts) if mapping["text"][1] else texts[0])
    put("target", target)
    put("source", source)
    put("formality", formality)
    put("context", context)
    put("glossary", glossary_id)
    return arguments


def extract_translations(result: Mapping[str, Any]) -> list[tuple[str, str | None]]:
    """Read ``(text, detected source language)`` pairs out of a ``tools/call`` result."""
    if result.get("isError"):
        raise ValueError(_content_text(result) or "The translation tool reported an error")
    payload = result.get("structuredContent")
    if payload is None:
        text = _content_text(result)
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text
    items = _items(payload)
    if not items:
        raise ValueError("The translation tool answered with nothing that looks like a translation")
    return items


def _content_text(result: Mapping[str, Any]) -> str:
    parts = [
        part.get("text", "")
        for part in result.get("content") or []
        if isinstance(part, Mapping) and part.get("type") == "text"
    ]
    return "\n".join(parts).strip()


def _items(payload: Any) -> list[tuple[str, str | None]]:
    if isinstance(payload, str):
        return [(payload, None)] if payload else []
    if isinstance(payload, list):
        found: list[tuple[str, str | None]] = []
        for entry in payload:
            found.extend(_items(entry))
        return found
    if isinstance(payload, Mapping):
        for key in ("translations", "results", "result"):
            if key in payload:
                return _items(payload[key])
        for key in _TEXT_KEYS:
            if isinstance(payload.get(key), str):
                detected = next((payload[k] for k in _DETECTED_KEYS if isinstance(payload.get(k), str)), None)
                return [(payload[key], detected)]
    return []


def infer_request_characters(tool_names: Sequence[str]) -> int:
    """Free accounts are not offered the glossary tools, which also tells their request limit."""
    return SEAT_PLAN_REQUEST_CHARACTERS if GLOSSARY_TOOL in tool_names else FREE_PLAN_REQUEST_CHARACTERS


def split_by_characters(texts: Sequence[str], max_characters: int, max_texts: int) -> list[list[str]]:
    """Group texts so that no group exceeds the character or count limit of one call."""
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for text in texts:
        if current and (len(current) >= max_texts or size + len(text) > max_characters):
            groups.append(current)
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        groups.append(current)
    return groups


# --- OAuth ---------------------------------------------------------------------------------------


def generate_code_verifier() -> str:
    """A PKCE code verifier (RFC 7636)."""
    return secrets.token_urlsafe(64)


def compute_code_challenge(verifier: str) -> str:
    """The S256 challenge belonging to a code verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def resource_metadata_url(www_authenticate: str | None) -> str | None:
    """The protected resource metadata URL a 401 answer points to (RFC 9728)."""
    if not www_authenticate:
        return None
    match = re.search(r'resource_metadata="([^"]+)"', www_authenticate)
    return match.group(1) if match else None


def registration_payload(client_name: str, redirect_uri: str, scope: str) -> dict[str, Any]:
    """The body of a dynamic client registration (RFC 7591) for a public client."""
    return {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": scope,
    }
