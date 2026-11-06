"""Services of the DeepL Translator integration.

Every service can hand its result back (``response_variable`` in automations and scripts,
``return_response`` for other integrations), which is what makes them usable as a
translation backend by anything else running in Home Assistant.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

try:
    from homeassistant.exceptions import ServiceValidationError
except ImportError:  # Home Assistant older than 2023.12
    ServiceValidationError = HomeAssistantError

from .api import DeepLAuthError, DeepLError, DeepLRequestError, TranslateOptions, Translation
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONTEXT,
    ATTR_DATA,
    ATTR_DRY_RUN,
    ATTR_FORMALITY,
    ATTR_FORMAT,
    ATTR_GLOSSARY_ID,
    ATTR_IGNORE_KEYS,
    ATTR_INPUT_FILE,
    ATTR_LANGUAGE_TYPE,
    ATTR_ONLY_KEYS,
    ATTR_OUTPUT_FILE,
    ATTR_OVERWRITE,
    ATTR_PROTECT_PLACEHOLDERS,
    ATTR_SKIP_TECHNICAL_VALUES,
    ATTR_SOURCE_LANGUAGE,
    ATTR_TAG_HANDLING,
    ATTR_TARGET_LANGUAGE,
    ATTR_TEXT,
    ATTR_TIMEOUT,
    DEFAULT_DOCUMENT_TIMEOUT,
    DOMAIN,
    FORMALITY_VALUES,
    LANGUAGE_TYPES,
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_TIMEOUT,
    MIN_DOCUMENT_TIMEOUT,
    SERVICE_GET_LANGUAGES,
    SERVICE_TRANSLATE_DOCUMENT,
    SERVICE_TRANSLATE_STRUCTURE,
    SERVICE_TRANSLATE_TEXT,
    STRUCTURE_FORMATS,
    STRUCTURE_SUFFIXES,
    SUPPORTED_DOCUMENT_EXTENSIONS,
    TAG_HANDLING_VALUES,
)
from . import placeholders, preflight, structured
from .data import DeepLRuntimeData
from .languages import (
    SOURCE_LANGUAGES,
    TARGET_LANGUAGES,
    normalize_source_language,
    normalize_target_language,
)
from .translator import async_run_plan, plan_translation

_ENTRY_FIELD = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

TRANSLATE_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TEXT): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1)),
        vol.Optional(ATTR_TARGET_LANGUAGE): cv.string,
        vol.Optional(ATTR_SOURCE_LANGUAGE): cv.string,
        vol.Optional(ATTR_FORMALITY, default="default"): vol.In(FORMALITY_VALUES),
        vol.Optional(ATTR_CONTEXT): cv.string,
        vol.Optional(ATTR_GLOSSARY_ID): cv.string,
        vol.Optional(ATTR_TAG_HANDLING, default="none"): vol.In(TAG_HANDLING_VALUES),
        **_ENTRY_FIELD,
    }
)

TRANSLATE_DOCUMENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_INPUT_FILE): cv.string,
        vol.Optional(ATTR_OUTPUT_FILE): cv.string,
        vol.Optional(ATTR_TARGET_LANGUAGE): cv.string,
        vol.Optional(ATTR_SOURCE_LANGUAGE): cv.string,
        vol.Optional(ATTR_FORMALITY, default="default"): vol.In(FORMALITY_VALUES),
        vol.Optional(ATTR_GLOSSARY_ID): cv.string,
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
        vol.Optional(ATTR_TIMEOUT, default=DEFAULT_DOCUMENT_TIMEOUT): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_DOCUMENT_TIMEOUT, max=MAX_DOCUMENT_TIMEOUT)
        ),
        **_ENTRY_FIELD,
    }
)

TRANSLATE_STRUCTURE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_DATA): vol.Any(dict, list),
        vol.Optional(ATTR_INPUT_FILE): cv.string,
        vol.Optional(ATTR_OUTPUT_FILE): cv.string,
        vol.Optional(ATTR_FORMAT, default="auto"): vol.In(STRUCTURE_FORMATS),
        vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
        vol.Optional(ATTR_ONLY_KEYS, default=list): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_IGNORE_KEYS, default=list): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_SKIP_TECHNICAL_VALUES, default=True): cv.boolean,
        vol.Optional(ATTR_PROTECT_PLACEHOLDERS, default=True): cv.boolean,
        vol.Optional(ATTR_DRY_RUN, default=False): cv.boolean,
        vol.Optional(ATTR_TARGET_LANGUAGE): cv.string,
        vol.Optional(ATTR_SOURCE_LANGUAGE): cv.string,
        vol.Optional(ATTR_FORMALITY, default="default"): vol.In(FORMALITY_VALUES),
        vol.Optional(ATTR_CONTEXT): cv.string,
        vol.Optional(ATTR_GLOSSARY_ID): cv.string,
        **_ENTRY_FIELD,
    }
)

GET_LANGUAGES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_LANGUAGE_TYPE, default="target"): vol.In(LANGUAGE_TYPES),
        **_ENTRY_FIELD,
    }
)

GET_USAGE_SCHEMA = vol.Schema({vol.Optional("refresh", default=False): cv.boolean, **_ENTRY_FIELD})


class DeepLServices:
    """Implements the services on top of the loaded config entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def register(self) -> None:
        """Make the services available; called once for the whole integration."""
        for name, handler, schema in (
            (SERVICE_TRANSLATE_TEXT, self.translate_text, TRANSLATE_TEXT_SCHEMA),
            (SERVICE_TRANSLATE_DOCUMENT, self.translate_document, TRANSLATE_DOCUMENT_SCHEMA),
            (SERVICE_TRANSLATE_STRUCTURE, self.translate_structure, TRANSLATE_STRUCTURE_SCHEMA),
            (SERVICE_GET_LANGUAGES, self.get_languages, GET_LANGUAGES_SCHEMA),
            ("get_usage", self.get_usage, GET_USAGE_SCHEMA),
        ):
            self._hass.services.async_register(
                DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL
            )

    async def translate_text(self, call: ServiceCall) -> dict[str, Any]:
        """Translate one or more texts."""
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        options = self._options(runtime, call.data)
        translations = await self._translate(runtime, call.data[ATTR_TEXT], options)
        return {
            "text": translations[0].text,
            "translations": [
                {"text": item.text, "detected_source_language": item.detected_source_language}
                for item in translations
            ],
            "target_language": options.target_lang,
        }

    async def translate_document(self, call: ServiceCall) -> dict[str, Any]:
        """Translate a file and store the result next to it or at the requested path."""
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        options = self._options(runtime, call.data)
        if not runtime.client.capabilities.documents:
            raise ServiceValidationError(
                "Document translation needs an account that signed in with an API key; "
                f"accounts that signed in with OAuth can only translate text. {preflight.NOTHING_SENT}"
            )
        input_file = Path(self._hass.config.path(call.data[ATTR_INPUT_FILE]))
        output_file = _output_path(
            self._hass, input_file, options.target_lang, call.data.get(ATTR_OUTPUT_FILE)
        )
        try:
            preflight.check_document_extension(input_file.suffix, SUPPORTED_DOCUMENT_EXTENSIONS)
        except preflight.PreflightError as err:
            raise ServiceValidationError(str(err)) from err

        content = await self._hass.async_add_executor_job(
            _read_input, self._hass, input_file, output_file, call.data[ATTR_OVERWRITE]
        )
        await self._preflight_request(runtime, options, needed_characters=1)
        try:
            document = await runtime.client.async_translate_document(
                content, input_file.name, options, call.data[ATTR_TIMEOUT]
            )
        except DeepLError as err:
            raise self._failure(runtime, err) from err
        await self._hass.async_add_executor_job(_write_output, output_file, document.content)
        await self._refresh_usage(runtime)
        return {
            "output_file": str(output_file),
            "target_language": options.target_lang,
            "document_id": document.document_id,
            "billed_characters": document.billed_characters,
        }

    async def translate_structure(self, call: ServiceCall) -> dict[str, Any]:
        """Translate only the text values of structured data, leaving its shape untouched.

        The data is either passed inline or read from a JSON or YAML file. Files keep their exact
        layout (indentation, key order, quoting, comments); inline data comes back as a copy.
        """
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        options = self._options(runtime, call.data)
        rules = structured.Rules(
            only_keys=frozenset(call.data[ATTR_ONLY_KEYS]),
            ignore_keys=frozenset(call.data[ATTR_IGNORE_KEYS]),
            skip_technical_values=call.data[ATTR_SKIP_TECHNICAL_VALUES],
        )
        inline = ATTR_DATA in call.data
        if inline == (ATTR_INPUT_FILE in call.data):
            raise ServiceValidationError(
                f"Give either '{ATTR_DATA}' or '{ATTR_INPUT_FILE}', not both and not neither"
            )
        dry_run = call.data[ATTR_DRY_RUN]

        document: _Document | None = None
        output_file: Path | None = None
        if inline:
            scan = structured.scan_object(call.data[ATTR_DATA], rules)
        else:
            input_file = Path(self._hass.config.path(call.data[ATTR_INPUT_FILE]))
            fmt = _structure_format(call.data[ATTR_FORMAT], input_file)
            if not dry_run:
                output_file = _output_path(
                    self._hass, input_file, options.target_lang, call.data.get(ATTR_OUTPUT_FILE)
                )
            document = await self._hass.async_add_executor_job(
                _read_structure, self._hass, input_file, output_file, call.data[ATTR_OVERWRITE], fmt, rules
            )
            scan = document.scan

        if dry_run:
            return {
                "dry_run": True,
                "strings": [
                    {"path": structured.render_path(slot.path), "text": slot.text} for slot in scan.slots
                ],
                "characters": sum(len(slot.text) for slot in scan.slots),
                "skipped_strings": scan.skipped,
                "characters_remaining": (
                    runtime.coordinator.data.characters_remaining if runtime.coordinator else None
                ),
            }

        translations = await self._translate_slots(
            runtime, scan.slots, options, call.data[ATTR_PROTECT_PLACEHOLDERS]
        )
        result: dict[str, Any] = {
            "target_language": options.target_lang,
            "translated_strings": len(scan.slots),
            "skipped_strings": scan.skipped,
        }
        if document is None:
            by_path = {slot.path: text for slot, text in zip(scan.slots, translations)}
            result["data"] = structured.rebuild_object(call.data[ATTR_DATA], by_path)
        else:
            await self._hass.async_add_executor_job(
                _write_structure, output_file, document, translations
            )
            result["output_file"] = str(output_file)
        return result

    async def _translate_slots(
        self,
        runtime: DeepLRuntimeData,
        slots: Sequence[structured.Slot],
        options: TranslateOptions,
        protect_placeholders: bool,
    ) -> list[str]:
        """Translate the texts of the slots, shielding placeholders such as ``{name}`` if asked to."""
        texts = [slot.text for slot in slots]
        if not texts:
            return []
        protect = protect_placeholders and any(placeholders.contains_placeholder(text) for text in texts)
        measure = len
        if protect:
            if not runtime.client.capabilities.tag_handling:
                raise ServiceValidationError(
                    "These texts contain placeholders, and protecting them needs an account that "
                    f"signed in with an API key. Set '{ATTR_PROTECT_PLACEHOLDERS}' to false to "
                    f"translate them as they are. {preflight.NOTHING_SENT}"
                )
            texts = [placeholders.protect(text) for text in texts]
            options = replace(options, tag_handling="xml", ignore_tags=(placeholders.IGNORED_TAG,))
            measure = lambda text: len(placeholders.restore(text))  # tags are not billed
        translations = await self._translate(runtime, texts, options, measure)
        results = [item.text for item in translations]
        return [placeholders.restore(text) for text in results] if protect else results

    async def _translate(
        self,
        runtime: DeepLRuntimeData,
        texts: Sequence[str],
        options: TranslateOptions,
        measure: Callable[[str], int] = len,
    ) -> list[Translation]:
        """Check the whole request, then translate it: either everything is sent, or nothing."""
        plan = plan_translation(runtime.cache, texts, options)
        if plan.missing:
            capabilities = runtime.client.capabilities
            try:
                preflight.check_text_sizes(
                    plan.pending_texts, capabilities.max_text_bytes, capabilities.max_request_characters
                )
            except preflight.PreflightError as err:
                raise ServiceValidationError(str(err)) from err
            await self._preflight_request(runtime, options, plan.characters(measure))
        try:
            translations, billed = await async_run_plan(runtime.client, runtime.cache, plan)
        except DeepLError as err:
            raise self._failure(runtime, err) from err
        if billed:
            await self._refresh_usage(runtime)
        return translations

    async def _preflight_request(
        self, runtime: DeepLRuntimeData, options: TranslateOptions, needed_characters: int
    ) -> None:
        """Languages, formality, markup support and quota; raises before anything is sent."""
        capabilities = runtime.client.capabilities
        try:
            if options.tag_handling != "none" and not capabilities.tag_handling:
                raise preflight.PreflightError(
                    "Markup handling needs an account that signed in with an API key. "
                    f"{preflight.NOTHING_SENT}"
                )
            await self._check_languages(runtime, options)
            await self._check_quota(runtime, needed_characters)
        except preflight.PreflightError as err:
            raise ServiceValidationError(str(err)) from err

    async def _check_languages(self, runtime: DeepLRuntimeData, options: TranslateOptions) -> None:
        """Compare the languages with what DeepL offers; if that cannot be read, let DeepL decide."""
        if not runtime.client.capabilities.languages:
            return
        try:
            targets = {item.code.upper(): item for item in await runtime.client.async_get_languages("target")}
            sources = (
                {item.code.upper() for item in await runtime.client.async_get_languages("source")}
                if options.source_lang
                else None
            )
        except DeepLError:
            return
        preflight.check_language(options.target_lang, targets, "target")
        if sources is not None:
            preflight.check_language(options.source_lang, sources, "source")
        preflight.check_formality(
            options.formality, targets[options.target_lang].supports_formality, options.target_lang
        )

    async def _check_quota(self, runtime: DeepLRuntimeData, needed: int) -> None:
        """Refuse a request the remaining quota cannot cover completely."""
        coordinator = runtime.coordinator
        if coordinator is None or coordinator.data is None or needed <= 0:
            return
        remaining = coordinator.data.characters_remaining
        if remaining is None or needed <= remaining:
            return
        # The figure may be stale, and reading the usage costs nothing: look again before refusing.
        await coordinator.async_refresh()
        if coordinator.last_update_success:
            usage = coordinator.data
            preflight.check_quota(needed, usage.characters_remaining, usage.end_time)

    async def _refresh_usage(self, runtime: DeepLRuntimeData) -> None:
        if runtime.coordinator is not None:
            await runtime.coordinator.async_request_refresh()

    def _failure(self, runtime: DeepLRuntimeData, err: DeepLError) -> HomeAssistantError:
        """Turn a DeepL error into a service error; a rejected sign-in also asks for a new one."""
        if isinstance(err, DeepLAuthError):
            runtime.entry.async_start_reauth(self._hass)
        return _as_home_assistant_error(err)

    async def get_usage(self, call: ServiceCall) -> dict[str, Any]:
        """Expose account usage without translating text; OAuth has no quota API."""
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        coordinator = runtime.coordinator
        if coordinator is None:
            return {"available": False, "reason": "unsupported"}
        if call.data.get("refresh"):
            await coordinator.async_refresh()
        if not coordinator.last_update_success or coordinator.data is None:
            return {"available": False, "reason": "unavailable"}
        usage = coordinator.data
        return {
            "available": True,
            "character_count": usage.character_count,
            "character_limit": None if usage.is_unlimited else usage.character_limit,
            "characters_remaining": usage.characters_remaining,
            "unlimited": usage.is_unlimited,
            "end_time": usage.end_time,
            "refreshed": bool(call.data.get("refresh")),
        }

    async def get_languages(self, call: ServiceCall) -> dict[str, Any]:
        """List the languages DeepL supports."""
        runtime = self._runtime(call.data.get(ATTR_CONFIG_ENTRY_ID))
        if not runtime.client.capabilities.languages:
            table = TARGET_LANGUAGES if call.data[ATTR_LANGUAGE_TYPE] == "target" else SOURCE_LANGUAGES
            return {
                "languages": [
                    {"code": code, "name": name, "supports_formality": None}
                    for code, name in table.items()
                ]
            }
        try:
            languages = await runtime.client.async_get_languages(call.data[ATTR_LANGUAGE_TYPE])
        except DeepLError as err:
            raise self._failure(runtime, err) from err
        return {
            "languages": [
                {
                    "code": language.code,
                    "name": language.name,
                    "supports_formality": language.supports_formality,
                }
                for language in languages
            ]
        }

    def _runtime(self, entry_id: str | None) -> DeepLRuntimeData:
        """The account a call is meant for: the named one, or the only one there is."""
        loaded: Mapping[str, DeepLRuntimeData] = self._hass.data.get(DOMAIN, {})
        if entry_id:
            if entry_id not in loaded:
                raise ServiceValidationError(f"The DeepL account {entry_id} is not loaded")
            return loaded[entry_id]
        if not loaded:
            raise ServiceValidationError("No DeepL account is set up")
        if len(loaded) > 1:
            raise ServiceValidationError(
                f"Several DeepL accounts are set up, choose one with '{ATTR_CONFIG_ENTRY_ID}'"
            )
        return next(iter(loaded.values()))

    @staticmethod
    def _options(runtime: DeepLRuntimeData, data: Mapping[str, Any]) -> TranslateOptions:
        """Turn the service fields into request options, filling in the account's default language."""
        source = data.get(ATTR_SOURCE_LANGUAGE)
        glossary_id = data.get(ATTR_GLOSSARY_ID)
        if glossary_id and not source:
            raise ServiceValidationError(
                f"A glossary needs '{ATTR_SOURCE_LANGUAGE}' as well, DeepL does not guess it then"
            )
        return TranslateOptions(
            target_lang=normalize_target_language(
                data.get(ATTR_TARGET_LANGUAGE) or runtime.default_target_language
            ),
            source_lang=normalize_source_language(source) if source else None,
            formality=data.get(ATTR_FORMALITY, "default"),
            context=data.get(ATTR_CONTEXT),
            glossary_id=glossary_id,
            tag_handling=data.get(ATTR_TAG_HANDLING, "none"),
        )


def _as_home_assistant_error(err: DeepLError) -> HomeAssistantError:
    """A refused request is the caller's mistake, everything else a failure of the service."""
    if isinstance(err, DeepLRequestError):
        return ServiceValidationError(f"DeepL: {err}")
    return HomeAssistantError(f"DeepL: {err}")


def _output_path(
    hass: HomeAssistant, input_file: Path, target_language: str, requested: str | None
) -> Path:
    """Default to ``report.pdf`` -> ``report.de.pdf`` next to the original."""
    if requested:
        return Path(hass.config.path(requested))
    return input_file.with_name(f"{input_file.stem}.{target_language.lower()}{input_file.suffix}")


def _read_input(
    hass: HomeAssistant, input_file: Path, output_file: Path | None, overwrite: bool
) -> bytes:
    """Check the paths and read the source; runs in the executor (blocking file access)."""
    for path in (input_file, output_file):
        if path is not None and not hass.config.is_allowed_path(str(path)):
            raise ServiceValidationError(
                f"{path} is not allowed, add its folder to allowlist_external_dirs "
                "or use a path inside the configuration folder"
            )
    if not input_file.is_file():
        raise ServiceValidationError(f"{input_file} does not exist or is not a file")
    if output_file is not None:
        if input_file.resolve() == output_file.resolve():
            raise ServiceValidationError("The output file must differ from the input file")
        if output_file.exists() and not overwrite:
            raise ServiceValidationError(
                f"{output_file} already exists, set '{ATTR_OVERWRITE}' to replace it"
            )
    if input_file.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ServiceValidationError(
            f"{input_file.name} is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB"
        )
    return input_file.read_bytes()


def _write_output(output_file: Path, content: bytes) -> None:
    """Store the result; a half written file never replaces a good one."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    partial = output_file.with_name(output_file.name + ".part")
    partial.write_bytes(content)
    partial.replace(output_file)


@dataclass(frozen=True)
class _Document:
    """A structured file as it was read: its text, whether it had a BOM, and what to translate."""

    text: str
    has_bom: bool
    fmt: str
    scan: structured.Scan


def _structure_format(requested: str, input_file: Path) -> str:
    """Use the requested format, or guess it from the file extension."""
    if requested != "auto":
        return requested
    if fmt := STRUCTURE_SUFFIXES.get(input_file.suffix.lower()):
        return fmt
    raise ServiceValidationError(
        f"Cannot tell the format of {input_file.name}, set '{ATTR_FORMAT}' to json or yaml"
    )


def _read_structure(
    hass: HomeAssistant,
    input_file: Path,
    output_file: Path | None,
    overwrite: bool,
    fmt: str,
    rules: structured.Rules,
) -> _Document:
    """Read and scan a structured file; runs in the executor."""
    raw = _read_input(hass, input_file, output_file, overwrite)
    try:
        text = raw.decode("utf-8-sig")
        scan = structured.scan_text(text, fmt, rules)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError) as err:
        raise ServiceValidationError(f"{input_file.name} is not valid {fmt.upper()}: {err}") from err
    return _Document(text, raw.startswith(b"\xef\xbb\xbf"), fmt, scan)


def _write_structure(output_file: Path, document: _Document, translations: Sequence[str]) -> None:
    """Splice the translations into the original text and store it; runs in the executor."""
    text = structured.apply_translations(document.text, document.scan, translations, document.fmt)
    _write_output(output_file, (("\ufeff" if document.has_bom else "") + text).encode("utf-8"))
