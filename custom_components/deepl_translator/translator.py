"""Translation with a cache in front of the backend, split into planning and doing.

Planning is free of side effects, so the caller can check the whole request (quota,
languages, sizes) before a single character is sent.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .api import TranslateOptions, Translation
from .backend import TranslationBackend
from .cache import TranslationCache
from .const import CACHE_MAX_TEXT_LENGTH


@dataclass
class TranslationPlan:
    """What a call needs from the backend once cached texts are taken out."""

    options: TranslateOptions
    results: list[Translation | None]
    missing: dict[str, list[int]]

    @property
    def pending_texts(self) -> list[str]:
        """The distinct texts DeepL has to translate."""
        return list(self.missing)

    def characters(self, measure: Callable[[str], int] = len) -> int:
        """How many characters the pending texts add up to."""
        return sum(measure(text) for text in self.missing)


def plan_translation(
    cache: TranslationCache[Translation], texts: Sequence[str], options: TranslateOptions
) -> TranslationPlan:
    """Sort the texts into empty ones, cached ones and the ones still to translate."""
    results: list[Translation | None] = [None] * len(texts)
    missing: dict[str, list[int]] = {}
    for index, text in enumerate(texts):
        if not text.strip():
            results[index] = Translation(text)
        elif (cached := cache.get((text, options))) is not None:
            results[index] = cached
        else:
            missing.setdefault(text, []).append(index)
    return TranslationPlan(options, results, missing)


async def async_run_plan(
    backend: TranslationBackend, cache: TranslationCache[Translation], plan: TranslationPlan
) -> tuple[list[Translation], bool]:
    """Translate what the plan is missing; also says whether DeepL was asked (and billed)."""
    if plan.missing:
        texts = plan.pending_texts
        for text, translation in zip(texts, await backend.async_translate(texts, plan.options)):
            for index in plan.missing[text]:
                plan.results[index] = translation
            if len(text) <= CACHE_MAX_TEXT_LENGTH:
                cache.put((text, plan.options), translation)
    return [item for item in plan.results if item is not None], bool(plan.missing)
