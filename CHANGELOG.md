# Changelog

## 1.0.0b1

- First beta of DeepL Translate for Home Assistant 2023.7 and newer, for free (`:fx`) and Pro API keys.
- Services `translate_text`, `translate_document`, `translate_structure` and `get_languages`, all of
  which return their result to the caller.
- `translate_structure` translates only the text values of JSON and YAML files or inline data and puts them back
  into the original layout (indentation, key order, quoting, comments); it can select keys, skip technical values,
  shield placeholders and do a `dry_run`.
- Usage sensors for characters used, limit, remaining, percent used and the end of the billing period.
- Default target language preselected from the server language; options for the usage refresh interval and the
  translation cache.
- Reauthentication when DeepL rejects the stored key, diagnostics without the API key, English and German
  translations.
