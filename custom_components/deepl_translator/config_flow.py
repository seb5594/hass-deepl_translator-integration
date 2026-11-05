"""Config flow for the DeepL Translator integration."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigEntryState,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

try:
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:  # Home Assistant older than 2024.4
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult

from .api import DeepLAuthError, DeepLConnectionError, DeepLError, TranslateOptions
from .const import (
    CONF_CACHE_SIZE,
    CONF_DISCOVER_TRANSLATOR,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_UPDATE_INTERVAL,
    DEFAULT_CACHE_SIZE,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FREE_KEY_SUFFIX,
    MAX_CACHE_SIZE,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
)
from .data import async_create_client, async_user_agent
from .mcp_client import DeepLMcpBackend
from .oauth import (
    DeepLOAuth2Implementation,
    RegisteredClient,
    async_discover,
    async_register_client,
    entry_client_data,
)
from .languages import (
    TARGET_LANGUAGES,
    normalize_target_language,
    target_from_home_assistant_language,
)


def _unique_id(api_key: str) -> str:
    """Identify an account without keeping the key itself in the registry."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _title(api_key: str) -> str:
    return "DeepL (Free)" if api_key.endswith(FREE_KEY_SUFFIX) else "DeepL (Pro)"


def _language_selector() -> SelectSelector:
    """A drop-down of the known targets that still accepts codes DeepL adds later."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=code, label=f"{name} ({code})")
                for code, name in TARGET_LANGUAGES.items()
            ],
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    )


def _api_key_schema(suggested_key: str | None = None) -> dict[Any, Any]:
    description = {"suggested_value": suggested_key} if suggested_key else None
    return {
        vol.Required(CONF_API_KEY, description=description): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }


class DeepLConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Set up a DeepL account with an API key or by signing in at DeepL."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._oauth_client: dict[str, Any] = {}

    @property
    def logger(self) -> logging.Logger:
        """Logger of the OAuth helper."""
        return logging.getLogger(__name__)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Offer the options of an existing entry."""
        return DeepLOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user choose how to sign in."""
        return self.async_show_menu(step_id="user", menu_options=["api_key", "oauth"])

    async def _async_check_key(self, api_key: str) -> str | None:
        """Return an error key when the API key does not work."""
        try:
            client = await async_create_client(self.hass, api_key)
            await client.async_get_usage()
        except DeepLAuthError:
            return "invalid_auth"
        except DeepLError:
            return "cannot_connect"
        except Exception:  # noqa: BLE001 - the form must stay usable whatever happens
            return "unknown"
        return None

    async def async_step_api_key(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the API key and the language to translate into by default."""
        errors: dict[str, str] = {}
        suggested_key = None
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            suggested_key = api_key
            await self.async_set_unique_id(_unique_id(api_key))
            self._abort_if_unique_id_configured()
            if error := await self._async_check_key(api_key):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=_title(api_key),
                    data={CONF_API_KEY: api_key},
                    options={
                        CONF_DEFAULT_TARGET_LANGUAGE: normalize_target_language(
                            user_input[CONF_DEFAULT_TARGET_LANGUAGE]
                        )
                    },
                )

        server_language = target_from_home_assistant_language(self.hass.config.language)
        schema = vol.Schema(
            {
                **_api_key_schema(suggested_key),
                vol.Required(
                    CONF_DEFAULT_TARGET_LANGUAGE, default=server_language
                ): _language_selector(),
            }
        )
        return self.async_show_form(step_id="api_key", data_schema=schema, errors=errors)

    async def async_step_oauth(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Register at DeepL and send the user there to log in."""
        session = async_get_clientsession(self.hass)
        try:
            endpoints = await async_discover(session)
            redirect_uri = DeepLOAuth2Implementation(
                self.hass, DOMAIN, RegisteredClient(""), endpoints
            ).redirect_uri
            client = await async_register_client(session, endpoints, redirect_uri)
        except DeepLConnectionError:
            return self.async_abort(reason="cannot_connect")
        except DeepLError as err:
            return self.async_abort(reason="oauth_unsupported", description_placeholders={"error": str(err)})
        except (NoURLAvailableError, RuntimeError):
            return self.async_abort(
                reason="no_url_available",
                description_placeholders={"docs_url": "https://www.home-assistant.io/more-info/no-url-available"},
            )
        implementation_id = f"{DOMAIN}_{hashlib.sha256(client.client_id.encode()).hexdigest()[:12]}"
        self.flow_impl = DeepLOAuth2Implementation(self.hass, implementation_id, client, endpoints)
        self._oauth_client = entry_client_data(implementation_id, client, endpoints)
        return await self.async_step_auth()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Check that translating works with the new sign-in, then keep it."""
        data = {**data, **self._oauth_client}
        access_token = data["token"]["access_token"]

        async def get_token() -> str:
            return access_token

        backend = DeepLMcpBackend(
            async_get_clientsession(self.hass), get_token, await async_user_agent(self.hass)
        )
        target = target_from_home_assistant_language(self.hass.config.language)
        try:
            await backend.async_connect()
            # One word proves the whole chain before the entry is created.
            await backend.async_translate(["Hello"], TranslateOptions(target_lang=target))
        except DeepLError as err:
            return self.async_abort(reason="translation_failed", description_placeholders={"error": str(err)})

        if self.source == SOURCE_REAUTH:
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            self.hass.config_entries.async_update_entry(entry, data={**entry.data, **data})
            if entry.state is not ConfigEntryState.LOADED:
                await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        await self.async_set_unique_id(data["client_id"])
        return self.async_create_entry(
            title="DeepL (OAuth)", data=data, options={CONF_DEFAULT_TARGET_LANGUAGE: target}
        )

    async def async_step_reauth(self, entry_data: Any) -> ConfigFlowResult:
        """Start when DeepL rejects the stored key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new key."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if CONF_API_KEY not in entry.data:
            return await self.async_step_reauth_oauth()
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if error := await self._async_check_key(api_key):
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_API_KEY: api_key},
                    title=_title(api_key),
                    unique_id=_unique_id(api_key),
                )
                # A loaded entry reloads through its update listener; the others need a nudge.
                if entry.state is not ConfigEntryState.LOADED:
                    await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(_api_key_schema()),
            description_placeholders={"account": entry.title},
            errors=errors,
        )


    async def async_step_reauth_oauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to sign in at DeepL again."""
        if user_input is None:
            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            return self.async_show_form(
                step_id="reauth_oauth", description_placeholders={"account": entry.title}
            )
        return await self.async_step_oauth()


class DeepLOptionsFlow(OptionsFlow):
    """Change the defaults of an account."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        # The entry id is the flow's handler in every Home Assistant version.
        entry = self.hass.config_entries.async_get_entry(self.handler)
        has_usage = CONF_API_KEY in entry.data  # accounts signed in with OAuth get no usage figures
        if user_input is not None:
            data = {
                **entry.options,
                CONF_DISCOVER_TRANSLATOR: user_input.get(CONF_DISCOVER_TRANSLATOR, entry.options.get(CONF_DISCOVER_TRANSLATOR, True)),
                CONF_DEFAULT_TARGET_LANGUAGE: normalize_target_language(
                    user_input[CONF_DEFAULT_TARGET_LANGUAGE]
                ),
                CONF_CACHE_SIZE: int(user_input[CONF_CACHE_SIZE]),
            }
            if has_usage:
                data[CONF_UPDATE_INTERVAL] = int(user_input[CONF_UPDATE_INTERVAL])
            return self.async_create_entry(title="", data=data)

        options = entry.options
        schema = vol.Schema(
            {
                vol.Required(CONF_DISCOVER_TRANSLATOR, default=options.get(CONF_DISCOVER_TRANSLATOR, True)): bool,
                vol.Required(
                    CONF_DEFAULT_TARGET_LANGUAGE,
                    default=options.get(
                        CONF_DEFAULT_TARGET_LANGUAGE,
                        target_from_home_assistant_language(self.hass.config.language),
                    ),
                ): _language_selector(),
                **(
                    {
                        vol.Required(
                            CONF_UPDATE_INTERVAL,
                            default=options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                        ): NumberSelector(
                            NumberSelectorConfig(
                                min=MIN_UPDATE_INTERVAL,
                                max=MAX_UPDATE_INTERVAL,
                                step=1,
                                mode=NumberSelectorMode.BOX,
                                unit_of_measurement="min",
                            )
                        )
                    }
                    if has_usage
                    else {}
                ),
                vol.Required(
                    CONF_CACHE_SIZE,
                    default=options.get(CONF_CACHE_SIZE, DEFAULT_CACHE_SIZE),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=MAX_CACHE_SIZE, step=1, mode=NumberSelectorMode.BOX
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
