"""Find the translatable texts in structured data and put translations back unchanged around them.

JSON and YAML documents are never parsed and re-written. They are only scanned for the position
of each string value, and the translations are spliced into the original text, so indentation,
key order, quoting, comments and anchors stay exactly as they were. Keys are never translated.

This module deliberately imports nothing from Home Assistant so it can be tested alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import re
from typing import Any

import yaml

Path = tuple[Any, ...]

MAX_JSON_DEPTH = 100
STR_TAG = "tag:yaml.org,2002:str"
BLOCK_STYLES = ("|", ">")

_JSON_STRING = re.compile(r'"(?:[^"\\\x00-\x1f]|\\.)*"', re.S)
_JSON_LITERAL = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null")
_JSON_UNICODE_ESCAPE = re.compile(r"\\u[0-9a-fA-F]{4}")

# Values that are identifiers or data rather than prose.
_TECHNICAL_VALUE = re.compile(
    r"""^(?:
        [a-zA-Z][a-zA-Z0-9+.-]*://\S+                 # URL
      | \S+@\S+\.\S+                                  # e-mail address
      | [a-z_][a-z0-9_]*\.[a-z0-9_]+                  # entity id such as sensor.kitchen_temp
      | [a-z0-9]+(?:_[a-z0-9]+)+                      # snake_case identifier
      | [a-z]+:[\w-]+                                 # icon such as mdi:lightbulb
      | \#[0-9a-fA-F]{3,8}                            # colour
      | v?\d+(?:\.\d+){1,3}[\w.+-]*                   # version number
      | [-+]?\d[\d.,:]*\s?[^\s\d]{1,3}                  # measurement such as 21.5 °C or 40%
    )$""",
    re.X,
)

# Anchors and tags in front of a scalar, which belong to its span but must survive.
_YAML_PROPERTIES = re.compile(r"(?:[&!][^\s]*[ \t]+)+")

# What may stay a plain (unquoted) YAML scalar after translation.
_PLAIN_SAFE = re.compile(r"[^\W_][\w .!?()/'-]*(?<! )", re.U)


@dataclass(frozen=True)
class Rules:
    """Which string values are worth translating."""

    only_keys: frozenset[str] = frozenset()
    ignore_keys: frozenset[str] = frozenset()
    skip_technical_values: bool = True

    def accepts(self, key: Any, value: str) -> bool:
        """Whether a string found below ``key`` should go to the translator."""
        if self.only_keys and key not in self.only_keys:
            return False
        if key in self.ignore_keys:
            return False
        if not any(char.isalpha() for char in value):
            return False
        return not (self.skip_technical_values and _TECHNICAL_VALUE.match(value.strip()))


@dataclass(frozen=True)
class Slot:
    """One string value of a document."""

    path: Path
    key: Any
    value: str
    span: tuple[int, int] | None = None
    style: str | None = None

    @property
    def text(self) -> str:
        """What is sent to the translator; block scalars lose their trailing line breaks."""
        return self.value.rstrip("\n") if self.style in BLOCK_STYLES else self.value


@dataclass(frozen=True)
class Scan:
    """The strings to translate and how many were left alone."""

    slots: list[Slot]
    skipped: int


def render_path(path: Path) -> str:
    """``("a", 0, "b")`` -> ``a[0].b``"""
    result = ""
    for part in path:
        result += f"[{part}]" if isinstance(part, int) else f"{'.' if result else ''}{part}"
    return result


def _select(candidates: Sequence[Slot], rules: Rules) -> Scan:
    chosen = [slot for slot in candidates if rules.accepts(slot.key, slot.text)]
    return Scan(chosen, len(candidates) - len(chosen))


# --- plain Python data (inline service data) ---------------------------------------------------


def scan_object(data: Any, rules: Rules) -> Scan:
    """Find the strings in nested dicts and lists."""
    found: list[Slot] = []

    def walk(node: Any, path: Path, key: Any) -> None:
        if isinstance(node, str):
            found.append(Slot(path, key, node))
        elif isinstance(node, Mapping):
            for name, child in node.items():
                walk(child, (*path, name), name)
        elif isinstance(node, (list, tuple)):
            for index, child in enumerate(node):
                walk(child, (*path, index), key)

    walk(data, (), None)
    return _select(found, rules)


def rebuild_object(data: Any, translations: Mapping[Path, str], path: Path = ()) -> Any:
    """A copy of the data with the translated strings put in; everything else is kept."""
    if isinstance(data, Mapping):
        return {name: rebuild_object(child, translations, (*path, name)) for name, child in data.items()}
    if isinstance(data, (list, tuple)):
        return [rebuild_object(child, translations, (*path, index)) for index, child in enumerate(data)]
    return translations.get(path, data) if isinstance(data, str) else data


# --- JSON text ---------------------------------------------------------------------------------


class _JsonScanner:
    """A minimal JSON reader that records where each string value starts and ends."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self.slots: list[Slot] = []

    def scan(self) -> list[Slot]:
        self._skip_whitespace()
        self._value((), None, 0)
        self._skip_whitespace()
        if self._pos != len(self._text):
            self._fail()
        return self.slots

    def _fail(self) -> None:
        raise ValueError(f"Invalid JSON near character {self._pos}")

    def _skip_whitespace(self) -> None:
        while self._pos < len(self._text) and self._text[self._pos] in " \t\r\n":
            self._pos += 1

    def _expect(self, char: str) -> None:
        if self._text[self._pos : self._pos + 1] != char:
            self._fail()
        self._pos += 1

    def _string(self) -> tuple[int, int, str]:
        match = _JSON_STRING.match(self._text, self._pos)
        if not match:
            self._fail()
        start, self._pos = self._pos, match.end()
        return start, self._pos, json.loads(match.group())

    def _value(self, path: Path, key: Any, depth: int) -> None:
        if depth > MAX_JSON_DEPTH:
            raise ValueError("The JSON is nested too deeply")
        char = self._text[self._pos : self._pos + 1]
        if char == "{":
            self._object(path, depth)
        elif char == "[":
            self._array(path, key, depth)
        elif char == '"':
            start, end, value = self._string()
            self.slots.append(Slot(path, key, value, (start, end)))
        else:
            match = _JSON_LITERAL.match(self._text, self._pos)
            if not match:
                self._fail()
            self._pos = match.end()

    def _object(self, path: Path, depth: int) -> None:
        self._expect("{")
        self._skip_whitespace()
        if self._text[self._pos : self._pos + 1] == "}":
            self._pos += 1
            return
        while True:
            self._skip_whitespace()
            name = self._string()[2]
            self._skip_whitespace()
            self._expect(":")
            self._skip_whitespace()
            self._value((*path, name), name, depth + 1)
            self._skip_whitespace()
            if self._text[self._pos : self._pos + 1] == ",":
                self._pos += 1
                continue
            self._expect("}")
            return

    def _array(self, path: Path, key: Any, depth: int) -> None:
        self._expect("[")
        self._skip_whitespace()
        if self._text[self._pos : self._pos + 1] == "]":
            self._pos += 1
            return
        index = 0
        while True:
            self._skip_whitespace()
            self._value((*path, index), key, depth + 1)
            index += 1
            self._skip_whitespace()
            if self._text[self._pos : self._pos + 1] == ",":
                self._pos += 1
                continue
            self._expect("]")
            return


def scan_json(text: str, rules: Rules) -> Scan:
    """Find the string values of a JSON document."""
    return _select(_JsonScanner(text).scan(), rules)


# --- YAML text ---------------------------------------------------------------------------------


def scan_yaml(text: str, rules: Rules) -> Scan:
    """Find the string values of a YAML document (custom tags such as ``!secret`` are left alone)."""
    found: dict[tuple[int, int], Slot] = {}
    seen: set[int] = set()

    def walk(node: yaml.Node, path: Path, key: Any) -> None:
        if id(node) in seen:  # an alias points at a node that was handled already
            return
        seen.add(id(node))
        if isinstance(node, yaml.ScalarNode):
            if node.tag == STR_TAG:
                span = (node.start_mark.index, node.end_mark.index)
                found[span] = Slot(path, key, node.value, span, node.style)
        elif isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                name = key_node.value if isinstance(key_node, yaml.ScalarNode) else None
                walk(value_node, (*path, name), name)
        elif isinstance(node, yaml.SequenceNode):
            for index, child in enumerate(node.value):
                walk(child, (*path, index), key)

    for document in yaml.compose_all(text, Loader=yaml.SafeLoader):
        if document is not None:
            walk(document, (), None)
    return _select(sorted(found.values(), key=lambda slot: slot.span), rules)


def _render_yaml_scalar(original: str, slot: Slot, value: str) -> str:
    """Write a translated value in the style of the original one, falling back to double quotes."""
    properties = _YAML_PROPERTIES.match(original)
    prefix = properties.group() if properties else ""
    original = original[len(prefix) :]
    trailing = original[len(original.rstrip("\n")) :]
    if slot.style in BLOCK_STYLES:
        header, _, body = original.rstrip("\n").partition("\n")
        first = next((line for line in body.split("\n") if line.strip()), None)
        if first is None or value[:1].isspace():
            return prefix + json.dumps(value, ensure_ascii=False) + trailing
        indent = first[: len(first) - len(first.lstrip(" "))]
        lines = "\n".join(f"{indent}{line}" if line else "" for line in value.split("\n"))
        return f"{prefix}{header}\n{lines}{trailing}"
    if slot.style == "'" and "\n" not in value:
        return prefix + "'" + value.replace("'", "''") + "'"
    if slot.style is None and _is_plain_safe(value):
        return prefix + value
    return prefix + json.dumps(value, ensure_ascii=False)


def _is_plain_safe(value: str) -> bool:
    if not _PLAIN_SAFE.fullmatch(value):
        return False
    try:
        return yaml.safe_load(value) == value  # "yes", "1.5" or "null" would change their type
    except yaml.YAMLError:
        return False


# --- putting translations back -----------------------------------------------------------------


def apply_translations(text: str, scan: Scan, translations: Sequence[str], fmt: str) -> str:
    """Splice the translations into the original document text, last position first."""
    ascii_only = fmt == "json" and bool(_JSON_UNICODE_ESCAPE.search(text))
    for slot, value in sorted(zip(scan.slots, translations), key=lambda pair: pair[0].span[0], reverse=True):
        if value == slot.text:  # untouched strings keep their exact original spelling
            continue
        start, end = slot.span
        if fmt == "json":
            replacement = json.dumps(value, ensure_ascii=ascii_only)
        else:
            replacement = _render_yaml_scalar(text[start:end], slot, value)
        text = text[:start] + replacement + text[end:]
    return text


def scan_text(text: str, fmt: str, rules: Rules) -> Scan:
    """Scan a document of the given format (``json`` or ``yaml``)."""
    return scan_json(text, rules) if fmt == "json" else scan_yaml(text, rules)
