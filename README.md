<!-- header:begin (generated from project metadata) -->
<h1 align="center">DeepL Translator</h1>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/seb5594/hass-deepl_translator-integration/main/custom_components/deepl_translator/brand/dark_logo@2x.png">
    <img src="https://raw.githubusercontent.com/seb5594/hass-deepl_translator-integration/main/custom_components/deepl_translator/brand/logo@2x.png" alt="DeepL Translator" width="320" height="160">
  </picture>
</p>

---

<p align="center">
  <a href="https://paypal.me/seb5594"><img src="https://img.shields.io/static/v1?label=Support&amp;message=PayPal&amp;color=0070BA&amp;logo=paypal&amp;logoColor=white&amp;style=for-the-badge" alt="PayPal" height="40"></a>
  <a href="https://buymeacoffee.com/seb5594"><img src="https://img.shields.io/static/v1?label=Support&amp;message=Buy%20Me%20a%20Coffee&amp;color=FFDD00&amp;logo=buy-me-a-coffee&amp;logoColor=black&amp;style=for-the-badge" alt="Buy Me a Coffee" height="40"></a><br>
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=seb5594&amp;repository=hass-deepl_translator-integration&amp;category=integration"><img src="https://img.shields.io/static/v1?label=HACS%20%C2%B7%20Marketplace&amp;message=Add%20integration&amp;color=41BDF5&amp;logo=homeassistantcommunitystore&amp;logoColor=white&amp;style=for-the-badge" alt="HACS · Marketplace" height="28"></a>
  <a href="https://github.com/seb5594/hass-deepl_translator-integration/actions/workflows/compat.yml"><img src="https://img.shields.io/static/v1?label=home%20assistant&amp;message=%E2%89%A5%202023.7.0&amp;color=1877A5&amp;style=for-the-badge" alt="home assistant" height="28"></a>
  <a href="https://github.com/seb5594/hass-deepl_translator-integration/releases/tag/v2026.11.06.1"><img src="https://img.shields.io/static/v1?label=version&amp;message=2026.11.06.1&amp;color=1877A5&amp;style=for-the-badge" alt="version" height="28"></a><br>
  <a href="https://github.com/seb5594/hass-deepl_translator-integration/releases"><img src="https://img.shields.io/github/downloads/seb5594/hass-deepl_translator-integration/v2026.11.06.1/total?label=downloads&amp;color=1877A5&amp;style=flat" alt="downloads" height="20"></a>
  <a href="https://github.com/seb5594/hass-deepl_translator-integration/issues"><img src="https://img.shields.io/github/issues/seb5594/hass-deepl_translator-integration?label=issues&amp;style=flat" alt="issues" height="20"></a>
  <img src="https://img.shields.io/static/v1?label=tests&amp;message=40%20passed&amp;color=2F855A&amp;style=flat" alt="tests" height="20">
  <a href="https://github.com/seb5594/hass-deepl_translator-integration/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/seb5594/hass-deepl_translator-integration/ci.yml?branch=main&amp;label=checks&amp;style=flat" alt="checks" height="20"></a>
  <a href="https://github.com/seb5594/hass-deepl_translator-integration#license"><img src="https://img.shields.io/github/license/seb5594/hass-deepl_translator-integration?label=license&amp;style=flat" alt="license" height="20"></a>
</p>
<!-- header:end -->

🇩🇪 [Deutsche Version](README.de.md)

Use [DeepL](https://www.deepl.com) from anywhere in Home Assistant: translate texts and files from
automations, scripts, dashboards or other integrations, and keep an eye on how much of your
character quota is left. It works with the free API plan (keys ending in `:fx`) as well as
with a regular DeepL API subscription.

## What you get

- **`deepl_translator.translate_text`**: one or many texts in, translations out. The result is
  returned to the caller, so any automation, script or integration can use it.
- **`deepl_translator.translate_document`**: translates a file (Word, PowerPoint, Excel, PDF,
  HTML, plain text and more) and saves it where you tell it to.
- **`deepl_translator.translate_structure`**: translates only the text values of JSON or YAML data
  (inline or from a file) and leaves keys, layout, comments and technical values alone.
- **`deepl_translator.get_languages`**: lists the languages DeepL currently supports.
- **Usage sensors**: characters used, limit, remaining, percent used and the end of the billing
  period. They tell you at a glance how much of the free quota is gone.
- **Sensible defaults**: the target language is preselected with the language of your Home
  Assistant server and can be changed at any time under *Configure*.
- **Two ways to sign in**: paste an API key, or log in at DeepL (OAuth) and copy nothing at all.
- **All or nothing**: a request is checked before anything is sent (quota, languages, formality,
  sizes, file types). If it cannot be translated completely you get a clear error, and nothing is
  sent or billed.
- **Easy on the quota**: identical texts are answered from a small in-memory cache instead of being
  billed twice, and the usage figures are read every 30 minutes (reading them is free).
- **Wide compatibility**: Home Assistant 2023.7 or newer, no extra Python packages and no extra
  container. The integration uses the HTTP session Home Assistant already shares.

## Why it talks to the DeepL API directly and not through MCP

DeepL offers MCP servers, and they are great for AI assistants. They are not a good foundation for
Home Assistant services, though:

| | DeepL remote MCP server | `deepl-mcp-server` (self-hosted) | This integration |
| --- | --- | --- | --- |
| Transport | Streamable HTTP | stdio | HTTPS (REST) |
| Authentication | OAuth sign-in with a DeepL account, no API key | `DEEPL_API_KEY` | `DEEPL_API_KEY` |
| Runs | at DeepL | as a Node.js process next to the assistant | inside Home Assistant |
| Made for | AI assistants | AI assistants | automations, scripts, other integrations |
| Quota display | no | no | yes |

- MCP tools are meant to be picked by a language model. They are not Home Assistant services, so an
  automation or another integration cannot call them reliably.
- As documented at the time of writing, Home Assistant's own MCP client speaks SSE with OAuth
  through application credentials and hands the tools to conversation agents only. It can reach
  neither the DeepL server (Streamable HTTP, dynamic client registration) nor a stdio server without
  a bridge in between.
- A self-hosted MCP server would add a Node.js process that sits idle most of the time, for exactly the
  same API key and the same quota.

So the integration calls the REST API itself. That is the lightest option, works with a plain API key
and gives every other integration a stable contract: a Home Assistant service that returns its
result. For people who would rather log in than copy a key, there is also an
[OAuth sign-in](#signing-in-with-oauth-experimental) that talks to DeepL's hosted MCP server, with
fewer features. Using DeepL's MCP servers with your AI assistants is a separate matter, described
[below](#using-deepl-with-ai-assistants-mcp).

## Installation

### HACS or Marketplace

1. Use the *HACS · Marketplace* badge above, or add this repository as a custom repository
   (category *Integration*): in HACS on Home Assistant 2026.10 and older, in
   **Settings → Marketplace** on 2026.11 and newer.
2. Install **DeepL Translator** and restart Home Assistant.

### Manual

Copy `custom_components/deepl_translator` into the `custom_components` folder of your configuration
(or unpack the ZIP of the latest release there) and restart Home Assistant.

## Setup

In Home Assistant open *Settings > Devices & services > Add integration*, pick **DeepL
Translator** and choose how to sign in.

### With an API key (full feature set)

1. Create an API key in your DeepL account under *Account > Keys and limits*. The free API plan
   covers 500,000 characters per month.
2. Choose *API key*, paste the key and check the default target language, which is preselected from
   your server language.

### Signing in with OAuth (experimental)

Choose *Sign in at DeepL*. Home Assistant registers itself at DeepL, sends you to DeepL's login page
and keeps the refresh token; no key is involved. A test translation of one word then proves that the
sign-in works before the account is added.

| | API key | OAuth |
| --- | --- | --- |
| `translate_text`, `translate_structure`, `get_languages` | yes | yes (the language list is built in) |
| `translate_document` | yes | no |
| Placeholder protection and markup handling | yes | no |
| Usage sensors and the quota check before sending | yes | no, DeepL offers no usage figures this way |
| Language and formality check before sending | against DeepL's live list | no |
| Request limit | 128 KiB per request | 5,000 characters (free) or 128,000 per request, split automatically |

What you need: Home Assistant must be reachable under an address DeepL can send your browser back to
(the [My Home Assistant](https://my.home-assistant.io) redirect, which most installations already
have, or an external URL). The sign-in uses DeepL's hosted MCP server; its OAuth endpoints, dynamic
client registration and PKCE support are read from the server's own metadata. This was written
against the published specifications and metadata, and DeepL has not documented the arguments of its
translation tool, so they are read from the tool's own schema. If anything differs, the test
translation fails and the account is not added. Please report what you see.

You can keep an API-key account next to an OAuth one and pick between them with `config_entry_id`.

You can add several accounts (for example a free and a Pro key). With more than one account,
service calls name the one to use with `config_entry_id`; with a single account nothing extra is
needed.

### Options

*Configure* on the integration lets you change:

| Option | Default | Meaning |
| --- | --- | --- |
| Default target language | server language | Used whenever a call does not name a target language |
| Usage refresh interval | 30 min | How often the quota is read (5 to 1440 minutes) |
| Translation cache size | 256 | Translations kept in memory, `0` turns the cache off |

## Entities

Every account gets one service device with these sensors:

| Sensor | Description |
| --- | --- |
| Characters used | Characters translated in the current billing period |
| Character limit | Quota of the period (diagnostic) |
| Characters remaining | What is left of the quota |
| Quota used | Share of the quota that is used up, in percent |
| Billing period end | When the counters reset (diagnostic, disabled by default) |

Accounts without a character cap report no limit, so limit, remaining and percent stay `unknown`
there. A quick dashboard card:

```yaml
type: gauge
entity: sensor.deepl_free_quota_used
name: DeepL quota
min: 0
max: 100
severity:
  green: 0
  yellow: 70
  red: 90
```

## Nothing is sent when the request cannot be completed

Before a request leaves Home Assistant, the whole request is checked, and a failed check raises a
clear error that ends with *Nothing was sent to DeepL.* The checks:

| Check | Refused when | Needs |
| --- | --- | --- |
| Quota | the characters still needed (cached texts do not count) exceed what is left; a stale figure is refreshed first, which is free | API key |
| Target and source language | DeepL does not list it; the error suggests close matches | API key |
| Formality | `more` or `less` is requested for a language without it (`prefer_more` and `prefer_less` are fine) | API key |
| Text size | a single text is too long for one request, however it is split | both |
| File type | the extension is not one DeepL translates | API key |
| Markup and placeholders | they are requested but the account cannot protect them | OAuth |
| Output file | it exists (without `overwrite`), equals the input, or lies outside the allowed folders | both |

If a check cannot be made (for example DeepL's language list is unreachable), the request goes ahead
and DeepL decides. A file translation writes its output only after every string came back.

## Services

### `deepl_translator.translate_text`

| Field | Required | Description |
| --- | --- | --- |
| `text` | yes | A text, or a list of texts |
| `target_language` | no | Target language, for example `DE`, `EN-GB`, `PT-BR`. Defaults to the language set up for the integration |
| `source_language` | no | Source language. Leave it out to let DeepL detect it |
| `formality` | no | `default`, `more`, `less`, `prefer_more`, `prefer_less` |
| `context` | no | Extra context that improves the result and is neither translated nor billed |
| `glossary_id` | no | A DeepL glossary; needs `source_language` |
| `tag_handling` | no | `xml` or `html` when the text contains markup |
| `config_entry_id` | no | The account to use when several are set up |

Response:

```yaml
text: Guten Morgen!              # the first translation, for the common single-text case
translations:
  - text: Guten Morgen!
    detected_source_language: EN
target_language: DE
```

Empty texts are returned unchanged and not sent to DeepL. Language codes are forgiving: `de`,
`pt_br` and `PT-BR` all work, and `EN` or `PT` are turned into `EN-US` and `PT-PT`.

### `deepl_translator.translate_document`

| Field | Required | Description |
| --- | --- | --- |
| `input_file` | yes | File to translate. Relative paths start in the configuration folder |
| `output_file` | no | Where to save the result. Defaults to the input name plus the language, e.g. `manual.de.docx` |
| `target_language`, `source_language`, `formality`, `glossary_id`, `config_entry_id` | no | As above |
| `overwrite` | no | Replace an existing output file (default: no, the call fails instead) |
| `timeout` | no | Seconds to wait for DeepL, 30 to 3600 (default 600) |

Both paths have to be inside the configuration folder or a folder listed in
[`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs).
The call waits until the translation is ready, which takes seconds for small files and longer for big
ones. Start it from a script (`script.turn_on`) when an automation should not wait for it. The response holds `output_file`,
`target_language`, `document_id` and `billed_characters`.

```yaml
action: deepl_translator.translate_document
data:
  input_file: /config/www/manual.docx
  output_file: /config/www/manual.de.docx
  target_language: DE
  overwrite: true
```

### `deepl_translator.translate_structure`

For configuration files, translation files, dashboards and other structured data. Plain text
goes to `translate_text`; this service reads the structure and sends **only the text values** to
DeepL, then puts the translations back, so the result looks exactly like the input. Keys are never
translated.

| Field | Required | Description |
| --- | --- | --- |
| `input_file` or `data` | one of them | A JSON or YAML file (relative paths start in the configuration folder), or data passed inline |
| `output_file` | no | Where to save a translated file. Defaults to the input name plus the language, e.g. `en.de.json` |
| `format` | no | `auto` (from the file extension, default), `json` or `yaml` |
| `only_keys` | no | Translate only values that belong to these keys, e.g. `[name, title, message]` |
| `ignore_keys` | no | Never translate values that belong to these keys |
| `skip_technical_values` | no | Leave URLs, entity IDs, icons, colors, versions and measurements alone (default: yes) |
| `protect_placeholders` | no | Keep `{name}`, `%s`, `${var}` and `{{ template }}` unchanged (default: yes) |
| `dry_run` | no | List what would be translated, with the character count, without contacting DeepL or writing anything |
| `overwrite` | no | Replace an existing output file (default: no) |
| `target_language`, `source_language`, `formality`, `context`, `glossary_id`, `config_entry_id` | no | As for `translate_text` |

What the service does with a file:

- **The layout stays.** JSON and YAML are not re-written from parsed data. Only the positions of
  the string values are found, and the translations are put in at exactly those places, so
  indentation, key order, quoting, comments, anchors and blank lines survive. YAML block scalars (`|`,
  `>`) keep their indentation, and a translation that would change a value's type (`yes`, `1.5`) or
  break the syntax (`: `, `#`) is quoted automatically. Strings DeepL leaves unchanged are not touched
  at all. YAML tags such as `!secret` and `!include` are left alone.
- **Only prose is sent.** Numbers, booleans, empty values and strings without letters are skipped,
  and with `skip_technical_values` so are URLs, e-mail addresses, entity IDs, snake_case
  identifiers, icons (`mdi:door`), colors, version numbers and measurements (`21.5 °C`).
- **Placeholders survive.** They are wrapped in a tag DeepL has been told to ignore, then unwrapped
  again. This switches the request to DeepL's XML mode when a text contains placeholders.
- **Quota friendly.** Identical strings are sent once and answered from the cache afterwards. Try
  `dry_run: true` first to see exactly what a file would cost.

> In configuration files most values are technical (`type: gauge`, `platform: template`). Use
> `only_keys` with the keys that hold text, for example `[name, title, message, description]`, and
> check the list with `dry_run`.

```yaml
action: deepl_translator.translate_structure
data:
  input_file: /config/custom_components/my_integration/translations/en.json
  output_file: /config/custom_components/my_integration/translations/de.json
  target_language: DE
  overwrite: true
```

Inline data is returned as a copy with the same shape; a file call returns the path instead:

```yaml
action: deepl_translator.translate_structure
data:
  data:
    title: Welcome
    icon: mdi:door
    buttons: [Open, Close]
  target_language: DE
response_variable: result
# result.data -> {title: Willkommen, icon: mdi:door, buttons: [Öffnen, Schließen]}
# result also has translated_strings and skipped_strings
```

The nearest key decides: for the items of a list that is the key holding the list. A `dry_run`
returns `strings: [{path, text}]` with paths such as `views[0].cards[1].title`, plus `characters`
and `skipped_strings`.

### `deepl_translator.get_languages`

Returns `languages: [{code, name, supports_formality}]` for `type: target` (default) or
`type: source`. The answer is cached for a day.

> Older automations written with `service:` instead of `action:` (Home Assistant before 2024.8) work
> the same way.

### `deepl_translator.get_usage`

The `deepl_translator.get_usage` action returns `available`, `character_count`, `character_limit`, `characters_remaining`, `unlimited`, `end_time` and `refreshed` for the selected `config_entry_id` (or the only loaded account). By default it reads cached usage. Set `refresh: true` to query the usage endpoint without translating text. Uncapped accounts have null limits and remaining characters. OAuth returns `available: false, reason: unsupported`; failed updates return `available: false, reason: unavailable`, rather than reporting a stale balance as current. Concurrent account use and provider reporting delays can still affect a fresh snapshot.

Custom Integration Translator 2026.11.06.1 uses this action for its quota preview. Translation remains compatible with older DeepL versions, which show an unknown balance.

## Recipes

### Translate a notification

```yaml
automation:
  - alias: Door left open (translated)
    triggers:
      - trigger: state
        entity_id: binary_sensor.front_door
        to: "on"
        for: "00:05:00"
    actions:
      - action: deepl_translator.translate_text
        data:
          text: "The front door has been open for five minutes."
          context: Short push notification
        response_variable: translated
      - action: notify.mobile_app_phone
        data:
          message: "{{ translated.text }}"
```

The automation uses the syntax of Home Assistant 2024.10 and newer (`triggers:`, `trigger: state`);
older versions write `trigger:` and `platform: state` instead.

### Use it from another integration

Call the service like any other and ask for the response. Declare
`"after_dependencies": ["deepl_translator"]` in your manifest and check that the service exists so
your integration keeps working without DeepL.

```python
if hass.services.has_service("deepl_translator", "translate_text"):
    response = await hass.services.async_call(
        "deepl_translator",
        "translate_text",
        {"text": message, "target_language": "DE"},
        blocking=True,
        return_response=True,
    )
    message = response["text"]
```

Failures arrive as `HomeAssistantError` (a rejected request, such as an unsupported language, as its
subclass `ServiceValidationError`), with DeepL's own message, for example about the exhausted quota.

### Translate text shown on a dashboard

Templates cannot call services, so let an automation do the work and keep the result in an
`input_text` that the card displays. Repeated texts cost nothing thanks to the cache.

```yaml
automation:
  - alias: Translate the daily tip
    triggers:
      - trigger: state
        entity_id: input_text.daily_tip
    actions:
      - action: deepl_translator.translate_text
        data:
          text: "{{ states('input_text.daily_tip') }}"
        response_variable: translated
      - action: input_text.set_value
        target:
          entity_id: input_text.daily_tip_translated
        data:
          value: "{{ translated.text }}"
```

## Using DeepL with AI assistants (MCP)

Everything above is for Home Assistant. If you also want an AI assistant to translate, DeepL's MCP
servers are the right tool. Exact menu names change between releases, so check the client's own
documentation if something looks different.

### DeepL's hosted MCP server (recommended, nothing to install)

URL: `https://mcp.deepl.com/v1/mcp` (Streamable HTTP). You sign in with your DeepL account through
OAuth, so there is no API key to manage. It uses the plan of the account and shows only the tools
the plan allows.

| Client | How |
| --- | --- |
| Claude (app) | *Settings > Connectors > Add custom connector*, paste the URL, sign in |
| Claude Code | `claude mcp add --transport http deepl https://mcp.deepl.com/v1/mcp`, then `/mcp` to sign in |
| ChatGPT | Enable developer mode, add a custom connector/app with the URL and sign in |
| Codex | `codex mcp add deepl --url https://mcp.deepl.com/v1/mcp`, then `codex mcp login deepl` |
| OpenClaw | Add the server under `mcp.servers` (see below), then `openclaw mcp login deepl` |

Codex can also read it from `~/.codex/config.toml`:

```toml
[mcp_servers.deepl]
url = "https://mcp.deepl.com/v1/mcp"
```

OpenClaw, following its configuration reference (verify with `openclaw config schema`):

```json
{
  "mcp": {
    "servers": {
      "deepl": {
        "url": "https://mcp.deepl.com/v1/mcp",
        "transport": "streamable-http",
        "auth": "oauth"
      }
    }
  }
}
```

### The self-hosted `deepl-mcp-server` (API key, runs locally)

[DeepL/deepl-mcp-server](https://github.com/DeepL/deepl-mcp-server) uses your API key and talks stdio,
so it suits assistants that start local tools. It needs Node.js 18 or newer.

```bash
claude mcp add deepl --env DEEPL_API_KEY=your-api-key -- npx -y deepl-mcp-server
```

```json
{
  "mcpServers": {
    "deepl": {
      "command": "npx",
      "args": ["-y", "deepl-mcp-server"],
      "env": { "DEEPL_API_KEY": "your-api-key" }
    }
  }
}
```

Compared with the hosted server it needs a local Node.js process and offers fewer tools (translate,
rephrase and read-only lookups), so choose it only when the OAuth sign-in is not an option.

### Letting an assistant use this integration through Home Assistant

An assistant can also reach DeepL through your Home Assistant, which counts against the same
quota that the sensors show:

1. Wrap the service in a script and expose it to Assist (*Settings > Voice assistants > Expose*):

   ```yaml
   script:
     translate_text:
       alias: Translate text with DeepL
       description: Translates a text into the given language and returns the result.
       fields:
         text:
           description: The text to translate
           example: Good morning
         language:
           description: Target language code
           example: DE
       sequence:
         - action: deepl_translator.translate_text
           data:
             text: "{{ text }}"
             target_language: "{{ language }}"
           response_variable: result
         - stop: Done
           response_variable: result
   ```

2. Enable the **Model Context Protocol Server** integration in Home Assistant and connect your
   assistant to `http://<your-home-assistant>:8123/api/mcp` (the URL is shown under *Settings >
   System > AI*). Assist's tools, including exposed scripts, become available to it, and the same
   script serves Assist's own conversation agents.

## Good to know

- The logo and icon are original artwork for this project: a house and two speech bubbles. They
  imitate neither DeepL's nor Home Assistant's logo. This is an unofficial integration, not made,
  endorsed or supported by DeepL SE or the Home Assistant project. DeepL is a trademark of DeepL SE
  and Home Assistant a trademark of the Open Home Foundation; both are named here only to say what
  the integration works with.

- Free accounts translate up to 500,000 characters per month. DeepL answers `456` once the quota is
  gone; the service then fails with a clear message instead of retrying.
- The `context` field is not billed. Documents are billed by DeepL's own rules, see the
  `billed_characters` of the response.
- If DeepL rejects the key (for example after you rotate it) Home Assistant shows a reauthentication
  notice where you enter the new key; nothing needs to be reinstalled.
- Download *Diagnostics* from the integration page for a bug report; the API key is removed from it.

## Development

The tests in `.github/tests` run anywhere with `python -m unittest discover -s .github/tests`.
The ones in `.github/ha_tests` run inside real Home Assistant releases from the minimum in
`hacs.json` upwards; see the [workflow engine](https://github.com/seb5594/hass-workflows) for the
matrix runner.

## Optional Custom Integration Translator

On Home Assistant 2023.7 or newer, a configured DeepL account detects an installed [Custom Integration Translator](https://github.com/seb5594/hass-custom_integrations_translator-integration) version 2026.11.05.4 or newer. After HACS/Marketplace installation or Home Assistant startup, a **Discovered** card in **Settings → Devices & services** offers setup. You choose whether to configure or ignore it. The companion is never downloaded automatically. Discovery uses installer events and startup, with no periodic polling or DeepL requests. Manually copied files need a Home Assistant restart.

Under **Configure → Discover Custom Integration Translator**, disable the setup suggestion for this account. Disable it on every DeepL account to stop discovery entirely. Pending confirmation cards are removed; manual setup, active translators and account-selection forms remain available.

<!-- support:begin (generated, shared text) -->
## Say thanks

All my projects are built in my spare time, just for the fun of it. Still, they take a lot of time and care, and many of the smart home gadgets I buy end up here because I want to make them cloud-free and smart-home ready. Every bit of support means a lot to me.

If my work helped you or turned out to be useful, show your appreciation with a hot drink for my next sleepless night.

[![PayPal](https://img.shields.io/static/v1?label=Support&message=PayPal&color=0070BA&logo=paypal&logoColor=white&style=for-the-badge)](https://paypal.me/seb5594) [![Buy Me a Coffee](https://img.shields.io/static/v1?label=Support&message=Buy%20Me%20a%20Coffee&color=FFDD00&logo=buy-me-a-coffee&logoColor=black&style=for-the-badge)](https://buymeacoffee.com/seb5594)
<!-- support:end -->

<!-- license:begin (generated from the license file) -->
## License

[![license](https://img.shields.io/static/v1?label=license&message=MIT&color=5B6770&style=flat)](LICENSE)

Published under the [MIT License](LICENSE).
<!-- license:end -->
