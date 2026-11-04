# Changelog

## 1.0.0b3

- Suggest setup under Devices & services after installation and restart, using this Home
  Assistant instance's own mDNS advertisement. Configured or ignored accounts are not prompted again.
- Accept an API key and optional language, polling interval and cache size in `configuration.yaml`,
  including `!secret`. Import into a normal config entry without duplicate accounts on restart;
  changing the YAML key updates the same managed account.

## 1.0.0b2

- The integration is now called DeepL Translator, its domain is `deepl_translator` and its services are
  `deepl_translator.*`. The repository was renamed to `hass-deepl_translator-integration`.
- Choose how to sign in: with an API key as before, or by logging in at DeepL (OAuth, experimental). The OAuth
  account translates text and structured data through DeepL's hosted MCP server; documents, usage sensors and
  placeholder protection need an API key.
- Requests are checked before anything is sent: quota, target and source language, formality, text sizes and file
  types. If a request cannot be translated completely, it fails with a clear message and nothing is sent or billed.
- Original icon and logo (a house with two speech bubbles) in `brand/`, with dark variants.
- Published under the MIT license.
- Shared checks, brand rendering and test helpers moved to the workflow engine.

## 1.0.0b1

- First beta of DeepL Translator for Home Assistant 2023.7 and newer, for free (`:fx`) and Pro API keys.
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
