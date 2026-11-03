"""Keep placeholders such as ``{name}`` or ``{{ states('x') }}`` out of the translation.

DeepL can leave XML tags alone (``ignore_tags``), so each placeholder is wrapped in one before
the text is sent, and the wrapper is removed from the answer. This module deliberately imports
nothing from Home Assistant so it can be tested alone.
"""

from __future__ import annotations

import re

IGNORED_TAG = "x"

_PLACEHOLDER = re.compile(
    r"""
    \{\{.*?\}\}                      # Jinja expression
  | \{%.*?%\}                        # Jinja statement
  | \{\#.*?\#\}                      # Jinja comment
  | \$\{[^}]*\}                      # ${name}
  | \{\w[\w.\[\]'"-]*\}              # {name}, {0}, {device.name}
  | %\([A-Za-z_]\w*\)[sdif]          # %(name)s
  | %[sdif]                          # %s
    """,
    re.X | re.S,
)
_WRAPPER = re.compile(rf"</?{IGNORED_TAG}\s*/?>")


def contains_placeholder(text: str) -> bool:
    """Whether the text has anything worth protecting."""
    return _PLACEHOLDER.search(text) is not None


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _unescape(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def protect(text: str) -> str:
    """Turn the text into XML in which every placeholder is wrapped in an ignored tag."""
    parts: list[str] = []
    position = 0
    for match in _PLACEHOLDER.finditer(text):
        parts.append(_escape(text[position : match.start()]))
        parts.append(f"<{IGNORED_TAG}>{_escape(match.group())}</{IGNORED_TAG}>")
        position = match.end()
    parts.append(_escape(text[position:]))
    return "".join(parts)


def restore(text: str) -> str:
    """Undo :func:`protect` on a translated text."""
    return _unescape(_WRAPPER.sub("", text))
