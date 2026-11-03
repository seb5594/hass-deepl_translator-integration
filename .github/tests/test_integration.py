"""Checks that need no Home Assistant installation."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - the shared setup installs PyYAML
    yaml = None

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = next((ROOT / "custom_components").iterdir())


def load_module(name):
    """Import a module of the component without importing (and needing) Home Assistant."""
    module_name = f"_isolated_{name}"
    spec = importlib.util.spec_from_file_location(module_name, COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def flatten(tree, prefix=""):
    """All key paths of a nested dict, ignoring the texts."""
    for key, value in tree.items():
        path = f"{prefix}{key}"
        yield path
        if isinstance(value, dict):
            yield from flatten(value, f"{path}.")


class IntegrationLayout(unittest.TestCase):
    def test_manifest_domain_matches_folder_and_constants(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], COMPONENT.name)
        self.assertIn(f'DOMAIN = "{COMPONENT.name}"', (COMPONENT / "const.py").read_text())

    def test_hacs_zip_is_named_after_the_domain(self):
        hacs = json.loads((ROOT / "hacs.json").read_text())
        self.assertEqual(hacs["filename"], f"{COMPONENT.name}.zip")

    def test_translations_mirror_strings(self):
        strings = json.loads((COMPONENT / "strings.json").read_text())
        english = json.loads((COMPONENT / "translations/en.json").read_text())
        self.assertEqual(strings, english)

    def test_german_translation_covers_every_english_key(self):
        english = json.loads((COMPONENT / "translations/en.json").read_text())
        german = json.loads((COMPONENT / "translations/de.json").read_text())
        self.assertEqual(sorted(flatten(english)), sorted(flatten(german)))

    def test_every_service_field_is_described(self):
        services = json.loads((COMPONENT / "translations/en.json").read_text())["services"]
        for name, service in services.items():
            self.assertTrue(service["name"] and service["description"], name)
            for field, texts in service["fields"].items():
                self.assertTrue(texts["name"] and texts["description"], f"{name}.{field}")


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class ServiceDefinitions(unittest.TestCase):
    def setUp(self):
        self.services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
        self.languages = load_module("languages")

    def test_fields_match_the_translations(self):
        texts = json.loads((COMPONENT / "translations/en.json").read_text())["services"]
        self.assertEqual(set(self.services), set(texts))
        for name, service in self.services.items():
            self.assertEqual(set(service["fields"]), set(texts[name]["fields"]), name)

    def test_language_menus_match_the_language_tables(self):
        for service in ("translate_text", "translate_document", "translate_structure"):
            fields = self.services[service]["fields"]
            for field, table in (
                ("target_language", self.languages.TARGET_LANGUAGES),
                ("source_language", self.languages.SOURCE_LANGUAGES),
            ):
                options = fields[field]["selector"]["select"]["options"]
                self.assertEqual([item["value"] for item in options], list(table), f"{service}.{field}")


class LanguageMapping(unittest.TestCase):
    def setUp(self):
        self.languages = load_module("languages")

    def test_home_assistant_languages_map_to_deepl_targets(self):
        expected = {
            "de": "DE",
            "en": "EN-US",
            "en-GB": "EN-GB",
            "en-AU": "EN-GB",
            "pt": "PT-PT",
            "pt-BR": "PT-BR",
            "no": "NB",
            "nb": "NB",
            "zh-Hans": "ZH-HANS",
            "zh-Hant": "ZH-HANT",
            "zh-TW": "ZH-HANT",
            "es-419": "ES-419",
            "es-MX": "ES",
            "de_AT": "DE",
            "fr-CA": "FR",
            "uk": "UK",
            "xx": "EN-US",
            "": "EN-US",
            None: "EN-US",
        }
        for language, target in expected.items():
            self.assertEqual(self.languages.target_from_home_assistant_language(language), target, language)

    def test_every_mapped_language_is_a_known_target(self):
        for language in ("de", "en", "pt", "no", "zh-Hans", "zh-Hant", "iw", "es-419"):
            code = self.languages.target_from_home_assistant_language(language)
            self.assertIn(code, self.languages.TARGET_LANGUAGES)

    def test_target_codes_are_normalized(self):
        normalize = self.languages.normalize_target_language
        self.assertEqual(normalize(" de "), "DE")
        self.assertEqual(normalize("pt_br"), "PT-BR")
        self.assertEqual(normalize("en"), "EN-US")
        self.assertEqual(normalize("PT"), "PT-PT")
        self.assertEqual(normalize("zh-hans"), "ZH-HANS")

    def test_source_codes_lose_their_region(self):
        normalize = self.languages.normalize_source_language
        self.assertEqual(normalize("en-US"), "EN")
        self.assertEqual(normalize("pt_br"), "PT")
        self.assertEqual(normalize("de"), "DE")


class TranslationCache(unittest.TestCase):
    def setUp(self):
        self.cache_type = load_module("cache").TranslationCache

    def test_least_recently_used_entry_is_dropped(self):
        cache = self.cache_type(2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)  # "b" is now the oldest
        cache.put("c", 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual((cache.get("a"), cache.get("c")), (1, 3))
        self.assertEqual(len(cache), 2)

    def test_size_zero_stores_nothing(self):
        cache = self.cache_type(0)
        cache.put("a", 1)
        self.assertFalse(cache.enabled)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(len(cache), 0)

    def test_clear_forgets_everything(self):
        cache = self.cache_type(5)
        cache.put("a", 1)
        cache.clear()
        self.assertIsNone(cache.get("a"))


class Placeholders(unittest.TestCase):
    def setUp(self):
        self.placeholders = load_module("placeholders")

    def test_every_placeholder_is_wrapped_and_comes_back_unchanged(self):
        for text in (
            "Hello {name}, you have {{ states('sensor.mail') }} new mails",
            "{% if x %}Open{% endif %} the door",
            "Battery at %d%% on %(device)s and ${level}",
            "Plain text without anything special",
            "Fish & chips <b>bold</b> {0}",
        ):
            with self.subTest(text=text):
                protected = self.placeholders.protect(text)
                self.assertEqual(self.placeholders.restore(protected), text)

    def test_placeholders_sit_in_ignored_tags_and_markup_is_escaped(self):
        protected = self.placeholders.protect("Hi {name} & <you>")
        self.assertEqual(protected, "Hi <x>{name}</x> &amp; &lt;you&gt;")

    def test_only_text_with_placeholders_needs_protection(self):
        self.assertTrue(self.placeholders.contains_placeholder("Hello {name}"))
        self.assertFalse(self.placeholders.contains_placeholder("Fish & chips"))
        self.assertFalse(self.placeholders.contains_placeholder("A {sentence in braces}"))


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class StructuredText(unittest.TestCase):
    YAML = """# Dashboard
title: Good morning   # greeting
views:
  - title: "Living room"
    icon: mdi:sofa
    cards:
      - type: markdown
        content: |
          Welcome home,
            {{ user }}!

          Enjoy.
        note: &note >-
          folded text
          continues here
      - name: 'It''s warm'
        entity: sensor.temp
        tags: [Cozy, "Very cozy"]
count: 5
enabled: true
empty:
anchor: &a Shared text
again: *a
tagged: !!str Plain tagged
last: Final line
"""
    JSON = '{\n    "title": "Hello",\n  "items": ["Open", {"label": "Caf\\u00e9"}], "n": 1.5e3, "e": {}, "l": [], "ok": true\n}\n'

    def setUp(self):
        self.structured = load_module("structured")
        self.rules = self.structured.Rules()

    def translate(self, text, fmt, rules=None, prefix="T: "):
        scan = self.structured.scan_text(text, fmt, rules or self.rules)
        translated = [prefix + slot.text for slot in scan.slots]
        return self.structured.apply_translations(text, scan, translated, fmt), scan

    def test_untouched_yaml_stays_byte_identical(self):
        scan = self.structured.scan_yaml(self.YAML, self.rules)
        same = self.structured.apply_translations(self.YAML, scan, [s.text for s in scan.slots], "yaml")
        self.assertEqual(same, self.YAML)

    def test_translated_yaml_keeps_comments_anchors_and_types(self):
        result, scan = self.translate(self.YAML, "yaml")
        self.assertIn("# Dashboard", result)
        self.assertIn("# greeting", result)
        self.assertIn("anchor: &a \"T: Shared text\"", result)
        self.assertIn("again: *a", result)
        self.assertIn("note: &note >-\n          T: folded text continues here", result)
        self.assertIn("tagged: !!str \"T: Plain tagged\"", result)
        data = yaml.safe_load(result)
        original = yaml.safe_load(self.YAML)
        self.assertEqual(data["count"], 5)
        self.assertIs(data["enabled"], True)
        self.assertIsNone(data["empty"])
        self.assertEqual(data["again"], "T: Shared text")
        card = data["views"][0]["cards"][0]
        self.assertEqual(card["content"], "T: Welcome home,\n  {{ user }}!\n\nEnjoy.\n")
        self.assertEqual(data["views"][0]["cards"][1]["name"], "T: It's warm")
        self.assertEqual(data["views"][0]["cards"][1]["tags"], ["T: Cozy", "T: Very cozy"])
        self.assertEqual(data["views"][0]["icon"], original["views"][0]["icon"])  # technical value
        self.assertEqual(list(data), list(original))

    def test_block_scalar_keeps_its_indentation_and_blank_lines(self):
        scan = self.structured.scan_yaml(self.YAML, self.rules)
        slot = next(s for s in scan.slots if s.key == "content")
        values = [("Willkommen,\n  {{ user }}!\n\nViel Spaß." if s is slot else s.text) for s in scan.slots]
        result = self.structured.apply_translations(self.YAML, scan, values, "yaml")
        self.assertEqual(yaml.safe_load(result)["views"][0]["cards"][0]["content"], "Willkommen,\n  {{ user }}!\n\nViel Spaß.\n")
        self.assertIn("        content: |\n          Willkommen,\n            {{ user }}!\n\n          Viel Spaß.\n        note:", result)

    def test_translations_that_would_change_the_yaml_type_get_quotes(self):
        text = "a: Yes please\nb: Maybe\n"
        scan = self.structured.scan_yaml(text, self.rules)
        result = self.structured.apply_translations(text, scan, ["yes", "1.5"], "yaml")
        self.assertEqual(yaml.safe_load(result), {"a": "yes", "b": "1.5"})
        scan = self.structured.scan_yaml("a: Hello\n", self.rules)
        result = self.structured.apply_translations("a: Hello\n", scan, ["Note: see #3, ok?"], "yaml")
        self.assertEqual(yaml.safe_load(result), {"a": "Note: see #3, ok?"})

    def test_custom_yaml_tags_are_left_alone(self):
        text = "password: !secret wifi\nname: !include name.yaml\ntitle: Home\n"
        scan = self.structured.scan_yaml(text, self.rules)
        self.assertEqual([slot.text for slot in scan.slots], ["Home"])

    def test_untouched_json_stays_byte_identical(self):
        scan = self.structured.scan_json(self.JSON, self.rules)
        self.assertEqual([slot.text for slot in scan.slots], ["Hello", "Open", "Café"])
        same = self.structured.apply_translations(self.JSON, scan, [s.text for s in scan.slots], "json")
        self.assertEqual(same, self.JSON)

    def test_translated_json_keeps_layout_and_escaping_style(self):
        result, _ = self.translate(self.JSON, "json", prefix="Ä ")
        self.assertEqual(
            result,
            '{\n    "title": "\\u00c4 Hello",\n  "items": ["\\u00c4 Open", {"label": "\\u00c4 Caf\\u00e9"}], '
            '"n": 1.5e3, "e": {}, "l": [], "ok": true\n}\n',
        )
        plain = '{"a": "x y"}'
        scan = self.structured.scan_json(plain, self.rules)
        self.assertEqual(self.structured.apply_translations(plain, scan, ['say "ö"'], "json"), '{"a": "say \\"ö\\""}')

    def test_invalid_documents_are_reported(self):
        for text in ('{"a": }', '{"a": "b",}', '["x"] trailing', "{'a': 1}"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.structured.scan_json(text, self.rules)
        with self.assertRaises(yaml.YAMLError):
            self.structured.scan_yaml("a: [unclosed\n", self.rules)

    def test_rules_choose_what_is_translated(self):
        document = json.dumps(
            {
                "name": "Kitchen light",
                "id": "kitchen_light",
                "entity_id": "light.kitchen",
                "url": "https://example.com/a",
                "color": "#ff00aa",
                "version": "1.2.3",
                "temperature": "21.5 °C",
                "message": "Door open",
                "icon": "mdi:door",
                "items": ["One", "Two"],
            }
        )
        names = lambda scan: [slot.key for slot in scan.slots]
        scan = self.structured.scan_json(document, self.rules)
        self.assertEqual(names(scan), ["name", "message", "items", "items"])
        self.assertEqual(scan.skipped, 7)
        only = self.structured.Rules(only_keys=frozenset({"message", "items"}))
        self.assertEqual(names(self.structured.scan_json(document, only)), ["message", "items", "items"])
        ignore = self.structured.Rules(ignore_keys=frozenset({"items"}))
        self.assertEqual(names(self.structured.scan_json(document, ignore)), ["name", "message"])
        technical = self.structured.Rules(skip_technical_values=False)
        self.assertIn("entity_id", names(self.structured.scan_json(document, technical)))

    def test_plain_data_is_rebuilt_without_touching_other_values(self):
        data = {"title": "Hello", "items": ["Open", 3, None, {"label": "Close"}], "n": 1.5}
        scan = self.structured.scan_object(data, self.rules)
        self.assertEqual([self.structured.render_path(s.path) for s in scan.slots], ["title", "items[0]", "items[3].label"])
        result = self.structured.rebuild_object(data, {s.path: s.text.upper() for s in scan.slots})
        self.assertEqual(result, {"title": "HELLO", "items": ["OPEN", 3, None, {"label": "CLOSE"}], "n": 1.5})
        self.assertEqual(data["title"], "Hello")


if __name__ == "__main__":
    unittest.main()
