"""Language codes understood by DeepL and the mapping from Home Assistant's own codes.

This module deliberately imports nothing from Home Assistant so it can be tested alone.
DeepL adds languages from time to time; the tables below only drive the drop-down menus,
any other code is passed through to the API, which has the final say.
"""

from __future__ import annotations

TARGET_LANGUAGES: dict[str, str] = {
    "AR": "Arabic",
    "BG": "Bulgarian",
    "CS": "Czech",
    "DA": "Danish",
    "DE": "German",
    "EL": "Greek",
    "EN-GB": "English (British)",
    "EN-US": "English (American)",
    "ES": "Spanish",
    "ES-419": "Spanish (Latin American)",
    "ET": "Estonian",
    "FI": "Finnish",
    "FR": "French",
    "HE": "Hebrew",
    "HU": "Hungarian",
    "ID": "Indonesian",
    "IT": "Italian",
    "JA": "Japanese",
    "KO": "Korean",
    "LT": "Lithuanian",
    "LV": "Latvian",
    "NB": "Norwegian (Bokmål)",
    "NL": "Dutch",
    "PL": "Polish",
    "PT-BR": "Portuguese (Brazilian)",
    "PT-PT": "Portuguese (European)",
    "RO": "Romanian",
    "RU": "Russian",
    "SK": "Slovak",
    "SL": "Slovenian",
    "SV": "Swedish",
    "TH": "Thai",
    "TR": "Turkish",
    "UK": "Ukrainian",
    "VI": "Vietnamese",
    "ZH": "Chinese",
    "ZH-HANS": "Chinese (Simplified)",
    "ZH-HANT": "Chinese (Traditional)",
}

SOURCE_LANGUAGES: dict[str, str] = {
    "AR": "Arabic",
    "BG": "Bulgarian",
    "CS": "Czech",
    "DA": "Danish",
    "DE": "German",
    "EL": "Greek",
    "EN": "English",
    "ES": "Spanish",
    "ET": "Estonian",
    "FI": "Finnish",
    "FR": "French",
    "HE": "Hebrew",
    "HU": "Hungarian",
    "ID": "Indonesian",
    "IT": "Italian",
    "JA": "Japanese",
    "KO": "Korean",
    "LT": "Lithuanian",
    "LV": "Latvian",
    "NB": "Norwegian (Bokmål)",
    "NL": "Dutch",
    "PL": "Polish",
    "PT": "Portuguese",
    "RO": "Romanian",
    "RU": "Russian",
    "SK": "Slovak",
    "SL": "Slovenian",
    "SV": "Swedish",
    "TH": "Thai",
    "TR": "Turkish",
    "UK": "Ukrainian",
    "VI": "Vietnamese",
    "ZH": "Chinese",
}

FALLBACK_TARGET_LANGUAGE = "EN-US"

# Home Assistant (BCP 47, lower case) codes that need an explicit choice.
_HOME_ASSISTANT_OVERRIDES = {
    "en": "EN-US",
    "pt": "PT-PT",
    "no": "NB",
    "iw": "HE",
    "zh-cn": "ZH-HANS",
    "zh-sg": "ZH-HANS",
    "zh-tw": "ZH-HANT",
    "zh-hk": "ZH-HANT",
}

# English regions that read more naturally as British English.
_BRITISH_ENGLISH_REGIONS = {"GB", "AU", "NZ", "IE", "ZA", "IN"}

# Plain codes that DeepL no longer accepts as a target.
_DEPRECATED_TARGETS = {"EN": "EN-US", "PT": "PT-PT"}


def _clean(code: str) -> str:
    return code.strip().replace("_", "-")


def normalize_target_language(code: str) -> str:
    """Return a target code in DeepL's upper case spelling, e.g. ``pt_br`` -> ``PT-BR``."""
    cleaned = _clean(code).upper()
    return _DEPRECATED_TARGETS.get(cleaned, cleaned)


def normalize_source_language(code: str) -> str:
    """Return a source code; sources never carry a region (``EN-US`` -> ``EN``)."""
    return _clean(code).upper().split("-")[0]


def target_from_home_assistant_language(language: str | None) -> str:
    """Pick the DeepL target that matches a Home Assistant language such as ``de`` or ``pt-BR``."""
    if not language:
        return FALLBACK_TARGET_LANGUAGE
    cleaned = _clean(language).lower()
    if cleaned in _HOME_ASSISTANT_OVERRIDES:
        return _HOME_ASSISTANT_OVERRIDES[cleaned]
    if cleaned.upper() in TARGET_LANGUAGES:
        return cleaned.upper()

    base, _, region = cleaned.partition("-")
    if base == "en":
        return "EN-GB" if region.upper() in _BRITISH_ENGLISH_REGIONS else "EN-US"
    if base in _HOME_ASSISTANT_OVERRIDES:
        return _HOME_ASSISTANT_OVERRIDES[base]
    if base.upper() in TARGET_LANGUAGES:
        return base.upper()
    return FALLBACK_TARGET_LANGUAGE
