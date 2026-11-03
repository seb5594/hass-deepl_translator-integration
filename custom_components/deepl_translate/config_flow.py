"""Config flow for the DeepL Translate integration."""

from __future__ import annotations

import hashlib
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
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

from .api import DeepLAuthError, DeepLError
from .const import (
    CONF_CACHE_SIZE,
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
from .data import async_create_client
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


class DeepLConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a DeepL account with its API key."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Offer the options of an existing entry."""
        return DeepLOptionsFlow()

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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Any) -> ConfigFlowResult:
        """Start when DeepL rejects the stored key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new key."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
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


class DeepLOptionsFlow(OptionsFlow):
    """Change the defaults of an account."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_DEFAULT_TARGET_LANGUAGE: normalize_target_language(
                        user_input[CONF_DEFAULT_TARGET_LANGUAGE]
                    ),
                    CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                    CONF_CACHE_SIZE: int(user_input[CONF_CACHE_SIZE]),
                },
            )

        # The entry id is the flow's handler in every Home Assistant version.
        options = self.hass.config_entries.async_get_entry(self.handler).options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_TARGET_LANGUAGE,
                    default=options.get(
                        CONF_DEFAULT_TARGET_LANGUAGE,
                        target_from_home_assistant_language(self.hass.config.language),
                    ),
                ): _language_selector(),
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
