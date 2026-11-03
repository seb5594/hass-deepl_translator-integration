"""Checks that run before anything is sent to DeepL.

A request that cannot be translated completely is refused up front with a clear message,
instead of being sent, billed and then failing halfway. Every message ends with the
sentence "Nothing was sent." because that is the promise these checks keep.

This module deliberately imports nothing from Home Assistant so it can be tested alone.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
import difflib

NOTHING_SENT = "Nothing was sent to DeepL."


class PreflightError(ValueError):
    """The request cannot be fulfilled completely; raised before anything is sent."""


def check_quota(needed: int, remaining: int | None, period_end: str | None = None) -> None:
    """Refuse when the remaining quota cannot cover the whole request."""
    if remaining is None or needed <= remaining:
        return
    until = f" until the quota resets on {period_end[:10]}" if period_end else ""
    raise PreflightError(
        f"Not enough DeepL quota: this request needs about {needed:,} characters but only "
        f"{remaining:,} are left{until}. {NOTHING_SENT}"
    )


def check_language(code: str, supported: Collection[str] | None, role: str) -> None:
    """Refuse a language DeepL does not offer; ``role`` is ``target`` or ``source``."""
    if not supported or code in supported:
        return
    direction = "into" if role == "target" else "from"
    close = difflib.get_close_matches(code, supported, n=3, cutoff=0.5)
    hint = f" Did you mean {', '.join(close)}?" if close else ""
    raise PreflightError(
        f"DeepL cannot translate {direction} '{code}'.{hint} "
        f"The service get_languages lists what is available. {NOTHING_SENT}"
    )


def check_formality(formality: str, supports_formality: bool | None, target: str) -> None:
    """Refuse a strict formality for a language that has none (the prefer_* values are fine)."""
    if formality in ("more", "less") and supports_formality is False:
        raise PreflightError(
            f"DeepL does not support formal or informal wording for '{target}'. Use 'default', "
            f"'prefer_more' or 'prefer_less', which are ignored for such languages. {NOTHING_SENT}"
        )


def check_text_sizes(
    texts: Iterable[str], max_bytes: int | None = None, max_characters: int | None = None
) -> None:
    """Refuse a single text that is too long for one request, however it is split."""
    for text in texts:
        if max_bytes is not None and len(text.encode("utf-8")) > max_bytes:
            raise PreflightError(
                f"A text of {len(text):,} characters is too long for one DeepL request (limit "
                f"about {max_bytes // 1000} KB). Split it into smaller texts. {NOTHING_SENT}"
            )
        if max_characters is not None and len(text) > max_characters:
            raise PreflightError(
                f"A text of {len(text):,} characters is longer than the {max_characters:,} "
                f"characters DeepL accepts per request on this account. Split it into smaller "
                f"texts. {NOTHING_SENT}"
            )


def check_document_extension(suffix: str, supported: Collection[str]) -> None:
    """Refuse a file type DeepL cannot translate."""
    if suffix.lower() in supported:
        return
    shown = suffix or "(no extension)"
    raise PreflightError(
        f"DeepL cannot translate {shown} files. Supported are: "
        f"{', '.join(sorted(supported))}. {NOTHING_SENT}"
    )
