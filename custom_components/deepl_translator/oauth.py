"""Sign in to DeepL with OAuth: discovery, dynamic client registration and token handling.

DeepL's hosted MCP server needs no API key. Home Assistant registers itself as a client at the
server (RFC 7591), sends the user to DeepL to log in, and keeps the refresh token. Everything
is learned from the server's own metadata (RFC 9728 and RFC 8414); nothing is hard-coded but
the address of the MCP server.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any
from urllib.parse import urljoin

import aiohttp
from yarl import URL

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import protocol
from .api import DeepLAuthError, DeepLConnectionError, DeepLError
from .const import (
    CONF_AUTHORIZE_URL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_TOKEN_URL,
    DOMAIN,
    MCP_URL,
    OAUTH_CLIENT_NAME,
    OAUTH_SCOPE,
    OAUTH_TIMEOUT,
)
from .data import async_user_agent
from .mcp_client import DeepLMcpBackend

_LOGGER = logging.getLogger(__name__)


class DeepLOAuthError(DeepLError):
    """The OAuth server does not behave the way this integration needs."""


@dataclass(frozen=True)
class OAuthEndpoints:
    """Where to send the user and the tokens requests."""

    authorize_url: str
    token_url: str
    registration_url: str


@dataclass(frozen=True)
class RegisteredClient:
    """The client the server created for this Home Assistant."""

    client_id: str
    client_secret: str | None = None


async def _get_json(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=OAUTH_TIMEOUT)) as response:
            if response.status >= 400:
                raise DeepLOAuthError(f"{url} answered with HTTP {response.status}")
            payload = await response.json(content_type=None)
    except asyncio.TimeoutError as err:
        raise DeepLConnectionError("Timed out while talking to DeepL") from err
    except aiohttp.ClientError as err:
        raise DeepLConnectionError(f"Cannot reach DeepL: {err}") from err
    if not isinstance(payload, dict):
        raise DeepLOAuthError(f"{url} did not answer with metadata")
    return payload


async def async_discover(session: aiohttp.ClientSession, mcp_url: str = MCP_URL) -> OAuthEndpoints:
    """Find the endpoints through the resource metadata the MCP server announces."""
    metadata_url = urljoin(mcp_url, "/.well-known/oauth-protected-resource")
    try:
        async with session.post(
            mcp_url,
            json=protocol.rpc_request(0, "ping"),
            headers={"Accept": "application/json, text/event-stream"},
            timeout=aiohttp.ClientTimeout(total=OAUTH_TIMEOUT),
        ) as response:
            if response.status == 401:
                metadata_url = (
                    protocol.resource_metadata_url(response.headers.get("WWW-Authenticate"))
                    or metadata_url
                )
    except asyncio.TimeoutError as err:
        raise DeepLConnectionError("Timed out while talking to DeepL") from err
    except aiohttp.ClientError as err:
        raise DeepLConnectionError(f"Cannot reach DeepL: {err}") from err

    resource = await _get_json(session, metadata_url)
    servers = resource.get("authorization_servers") or []
    if not servers:
        raise DeepLOAuthError("The MCP server names no authorization server")
    issuer = str(servers[0]).rstrip("/")
    server = await _get_json(session, f"{issuer}/.well-known/oauth-authorization-server")

    methods = server.get("code_challenge_methods_supported")
    if methods is not None and "S256" not in methods:
        raise DeepLOAuthError("The authorization server does not support PKCE with S256")
    try:
        return OAuthEndpoints(
            server["authorization_endpoint"], server["token_endpoint"], server["registration_endpoint"]
        )
    except KeyError as err:
        raise DeepLOAuthError(f"The authorization server metadata lacks {err}") from err


async def async_register_client(
    session: aiohttp.ClientSession, endpoints: OAuthEndpoints, redirect_uri: str
) -> RegisteredClient:
    """Register Home Assistant as a public client."""
    body = protocol.registration_payload(OAUTH_CLIENT_NAME, redirect_uri, OAUTH_SCOPE)
    try:
        async with session.post(
            endpoints.registration_url, json=body, timeout=aiohttp.ClientTimeout(total=OAUTH_TIMEOUT)
        ) as response:
            payload = await response.json(content_type=None)
            if response.status >= 400 or not isinstance(payload, dict) or "client_id" not in payload:
                reason = payload.get("error_description") or payload.get("error") if isinstance(payload, dict) else ""
                raise DeepLOAuthError(
                    f"DeepL refused the client registration (HTTP {response.status}) {reason}".strip()
                )
    except asyncio.TimeoutError as err:
        raise DeepLConnectionError("Timed out while talking to DeepL") from err
    except aiohttp.ClientError as err:
        raise DeepLConnectionError(f"Cannot reach DeepL: {err}") from err
    return RegisteredClient(payload["client_id"], payload.get("client_secret") or None)


class DeepLOAuth2Implementation(config_entry_oauth2_flow.LocalOAuth2Implementation):
    """The standard authorization-code flow plus PKCE, which DeepL requires."""

    def __init__(
        self,
        hass: HomeAssistant,
        implementation_id: str,
        client: RegisteredClient,
        endpoints: OAuthEndpoints,
    ) -> None:
        super().__init__(
            hass,
            implementation_id,
            client.client_id,
            client.client_secret,
            endpoints.authorize_url,
            endpoints.token_url,
        )
        self._verifiers: dict[str, str] = {}

    @property
    def name(self) -> str:
        """Shown to the user."""
        return "DeepL"

    @property
    def extra_authorize_data(self) -> dict:
        """Ask for a refresh token and name the server the token is for (RFC 8707)."""
        return {"scope": OAUTH_SCOPE, "resource": MCP_URL}

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        """The login address, with the PKCE challenge added."""
        verifier = protocol.generate_code_verifier()
        self._verifiers[flow_id] = verifier
        url = await super().async_generate_authorize_url(flow_id)
        return str(
            URL(url).update_query(
                {
                    "code_challenge": protocol.compute_code_challenge(verifier),
                    "code_challenge_method": "S256",
                }
            )
        )

    async def async_resolve_external_data(self, external_data: Any) -> dict:
        """Trade the authorization code for tokens, proving the PKCE verifier."""
        flow_id = external_data["state"]["flow_id"]
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": external_data["code"],
                "redirect_uri": external_data["state"]["redirect_uri"],
                "code_verifier": self._verifiers.pop(flow_id, ""),
            }
        )


def entry_client_data(
    implementation_id: str, client: RegisteredClient, endpoints: OAuthEndpoints
) -> dict[str, Any]:
    """What a config entry has to remember to rebuild the implementation after a restart."""
    return {
        "auth_implementation": implementation_id,
        CONF_CLIENT_ID: client.client_id,
        CONF_CLIENT_SECRET: client.client_secret,
        CONF_AUTHORIZE_URL: endpoints.authorize_url,
        CONF_TOKEN_URL: endpoints.token_url,
    }


def implementation_from_entry(hass: HomeAssistant, entry: ConfigEntry) -> DeepLOAuth2Implementation:
    """Rebuild the implementation a stored entry was created with."""
    data = entry.data
    return DeepLOAuth2Implementation(
        hass,
        data.get("auth_implementation", DOMAIN),
        RegisteredClient(data[CONF_CLIENT_ID], data.get(CONF_CLIENT_SECRET)),
        OAuthEndpoints(data[CONF_AUTHORIZE_URL], data[CONF_TOKEN_URL], ""),
    )


async def async_create_oauth_backend(hass: HomeAssistant, entry: ConfigEntry) -> DeepLMcpBackend:
    """A backend that refreshes the entry's token whenever it is about to expire."""
    oauth_session = config_entry_oauth2_flow.OAuth2Session(
        hass, entry, implementation_from_entry(hass, entry)
    )

    async def get_token() -> str:
        try:
            await oauth_session.async_ensure_token_valid()
        except aiohttp.ClientResponseError as err:
            if err.status in (400, 401, 403):
                raise DeepLAuthError("DeepL no longer accepts the sign-in") from err
            raise DeepLConnectionError(f"Cannot refresh the DeepL sign-in: {err}") from err
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise DeepLConnectionError(f"Cannot refresh the DeepL sign-in: {err}") from err
        return oauth_session.token["access_token"]

    return DeepLMcpBackend(
        async_get_clientsession(hass), get_token, await async_user_agent(hass)
    )
