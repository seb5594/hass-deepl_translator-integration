"""Translation with a cache in front of the API."""

from __future__ import annotations

from collections.abc import Sequence

from .api import DeepLClient, TranslateOptions, Translation
from .cache import TranslationCache
from .const import CACHE_MAX_TEXT_LENGTH


async def async_translate_texts(
    client: DeepLClient,
    cache: TranslationCache[Translation],
    texts: Sequence[str],
    options: TranslateOptions,
) -> tuple[list[Translation], bool]:
    """Translate texts in order and say whether DeepL had to be asked (and billed).

    Empty texts come back unchanged, texts seen before come from the cache and only
    the rest is sent to DeepL, in as few requests as possible.
    """
    results: list[Translation | None] = [None] * len(texts)
    missing: dict[str, list[int]] = {}

    for index, text in enumerate(texts):
        if not text.strip():
            results[index] = Translation(text)
        elif (cached := cache.get((text, options))) is not None:
            results[index] = cached
        else:
            missing.setdefault(text, []).append(index)

    if missing:
        unique_texts = list(missing)
        for text, translation in zip(unique_texts, await client.async_translate(unique_texts, options)):
            for index in missing[text]:
                results[index] = translation
            if len(text) <= CACHE_MAX_TEXT_LENGTH:
                cache.put((text, options), translation)

    return [item for item in results if item is not None], bool(missing)
