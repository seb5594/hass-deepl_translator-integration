# DeepL Translator für Home Assistant

🇬🇧 [English version](README.md)

DeepL überall in Home Assistant nutzen: Texte und Dateien aus Automatisierungen, Skripten,
Dashboards oder anderen Integrationen übersetzen und im Blick behalten, wie viel vom Zeichenkontingent
noch übrig ist. Die Integration funktioniert mit dem kostenlosen API-Tarif (Schlüssel enden auf `:fx`)
und mit einem regulären DeepL-API-Abo.

## Das bekommst du

- **`deepl_translator.translate_text`**: ein oder mehrere Texte hinein, Übersetzungen heraus. Das
  Ergebnis geht an den Aufrufer zurück, daher kann jede Automatisierung, jedes Skript und jede
  Integration es verwenden.
- **`deepl_translator.translate_document`**: übersetzt eine Datei (Word, PowerPoint, Excel, PDF, HTML,
  Text und mehr) und speichert sie, wo du es festlegst.
- **`deepl_translator.translate_structure`**: übersetzt nur die Textwerte von JSON- oder YAML-Daten
  (inline oder aus einer Datei) und lässt Schlüssel, Layout, Kommentare und technische Werte in Ruhe.
- **`deepl_translator.get_languages`**: listet die aktuell unterstützten Sprachen auf.
- **Verbrauchssensoren**: verbrauchte Zeichen, Limit, Rest, Prozent und Ende des Abrechnungszeitraums.
  Beim kostenlosen Tarif siehst du so sofort, wie viel vom Kontingent weg ist.
- **Sinnvolle Voreinstellungen**: Die Zielsprache ist mit der Sprache deines Home-Assistant-Servers
  vorausgewählt und lässt sich jederzeit unter *Konfigurieren* ändern.
- **Zwei Anmeldewege**: API-Schlüssel einfügen oder bei DeepL anmelden (OAuth), ganz ohne Kopieren.
- **Ganz oder gar nicht**: Eine Anfrage wird geprüft, bevor etwas gesendet wird (Kontingent, Sprachen, Anrede,
  Größen, Dateitypen). Lässt sie sich nicht vollständig übersetzen, gibt es eine klare Fehlermeldung, und es wird
  nichts gesendet oder berechnet.
- **Schont das Kontingent**: Identische Texte werden aus einem kleinen Speicher-Cache beantwortet statt
  doppelt berechnet, und der Verbrauch wird alle 30 Minuten abgefragt (die Abfrage ist kostenlos).
- **Breite Kompatibilität**: Home Assistant 2023.7 oder neuer, keine zusätzlichen Python-Pakete und kein
  zusätzlicher Container. Die Integration nutzt die HTTP-Sitzung, die Home Assistant ohnehin teilt.

## Warum die DeepL-API direkt und nicht über MCP

DeepL bietet MCP-Server an, die sich hervorragend für KI-Assistenten eignen. Als Grundlage für
Home-Assistant-Services taugen sie aber nicht:

| | Gehosteter DeepL-MCP-Server | `deepl-mcp-server` (selbst gehostet) | Diese Integration |
| --- | --- | --- | --- |
| Transport | Streamable HTTP | stdio | HTTPS (REST) |
| Anmeldung | OAuth mit DeepL-Konto, kein API-Schlüssel | `DEEPL_API_KEY` | `DEEPL_API_KEY` |
| Läuft | bei DeepL | als Node.js-Prozess neben dem Assistenten | in Home Assistant |
| Gedacht für | KI-Assistenten | KI-Assistenten | Automatisierungen, Skripte, andere Integrationen |
| Kontingentanzeige | nein | nein | ja |

- MCP-Werkzeuge sind dafür gedacht, von einem Sprachmodell ausgewählt zu werden. Es sind keine
  Home-Assistant-Services, daher kann sie eine Automatisierung oder eine andere Integration nicht
  zuverlässig aufrufen.
- Nach der aktuellen Dokumentation spricht der MCP-Client von Home Assistant SSE mit OAuth über
  Application Credentials und reicht die Werkzeuge nur an Konversations-Agenten weiter. Weder den
  DeepL-Server (Streamable HTTP, Dynamic Client Registration) noch einen stdio-Server erreicht er ohne
  Brücke dazwischen.
- Ein selbst gehosteter MCP-Server wäre ein zusätzlicher Node.js-Prozess, der meist untätig herumsteht,
  für denselben API-Schlüssel und dasselbe Kontingent.

Deshalb ruft die Integration die REST-API selbst auf. Das ist die leichteste Lösung, funktioniert mit einem
einfachen API-Schlüssel und gibt jeder anderen Integration einen stabilen Vertrag: einen Home-Assistant-Service,
der sein Ergebnis zurückgibt. Wer sich lieber anmeldet, als einen Schlüssel zu kopieren, kann die
[OAuth-Anmeldung](#anmeldung-mit-oauth-experimentell) nutzen, die mit dem gehosteten MCP-Server von DeepL spricht,
mit weniger Funktionen. Die MCP-Server von DeepL für deine KI-Assistenten sind ein eigenes Thema und werden
[weiter unten](#deepl-mit-ki-assistenten-mcp) beschrieben.

## Installation

### HACS oder Marketplace

1. Füge dieses Repository als benutzerdefiniertes Repository hinzu (Kategorie *Integration*): in HACS
   bis Home Assistant 2026.10, unter **Einstellungen → Marketplace** ab 2026.11.
2. Installiere **DeepL Translator** und starte Home Assistant neu.

### Manuell

Kopiere `custom_components/deepl_translator` in den Ordner `custom_components` deiner Konfiguration (oder
entpacke dort die ZIP-Datei der neuesten Version) und starte Home Assistant neu.

## Einrichtung

Öffne in Home Assistant *Einstellungen > Geräte & Dienste > Integration hinzufügen*, wähle **DeepL Translator**
und entscheide, wie du dich anmeldest.

### Mit API-Schlüssel (voller Funktionsumfang)

1. Erstelle in deinem DeepL-Konto unter *Konto > Schlüssel und Limits* einen API-Schlüssel. Der kostenlose
   API-Tarif umfasst 500.000 Zeichen pro Monat.
2. Wähle *API-Schlüssel*, füge den Schlüssel ein und prüfe die Standard-Zielsprache, die aus deiner Serversprache
   vorausgewählt wird.

### Anmeldung mit OAuth (experimentell)

Wähle *Bei DeepL anmelden*. Home Assistant registriert sich bei DeepL, leitet dich zur Anmeldeseite von DeepL und
merkt sich das Refresh-Token; ein Schlüssel kommt nicht vor. Eine Testübersetzung eines Wortes beweist danach, dass
die Anmeldung funktioniert, bevor das Konto hinzugefügt wird.

| | API-Schlüssel | OAuth |
| --- | --- | --- |
| `translate_text`, `translate_structure`, `get_languages` | ja | ja (die Sprachliste ist eingebaut) |
| `translate_document` | ja | nein |
| Platzhalterschutz und Markup-Behandlung | ja | nein |
| Verbrauchssensoren und Kontingentprüfung vor dem Senden | ja | nein, DeepL liefert so keine Verbrauchswerte |
| Sprach- und Anredeprüfung vor dem Senden | anhand der Live-Liste von DeepL | nein |
| Anfragelimit | 128 KiB pro Anfrage | 5.000 Zeichen (kostenlos) bzw. 128.000 pro Anfrage, automatisch aufgeteilt |

Voraussetzung: Home Assistant muss unter einer Adresse erreichbar sein, auf die DeepL deinen Browser zurückleiten
kann (die Weiterleitung von [My Home Assistant](https://my.home-assistant.io), die die meisten Installationen
haben, oder eine externe URL). Die Anmeldung nutzt den gehosteten MCP-Server von DeepL; OAuth-Endpunkte, Dynamic
Client Registration und PKCE-Unterstützung werden aus den Metadaten des Servers gelesen. Das wurde anhand der
veröffentlichten Spezifikationen und Metadaten geschrieben, und DeepL hat die Argumente seines Übersetzungs-Tools
nicht dokumentiert, daher werden sie aus dem Schema des Tools gelesen. Weicht etwas ab, schlägt die Testübersetzung
fehl und das Konto wird nicht hinzugefügt. Melde bitte, was du siehst.

Du kannst ein API-Schlüssel-Konto neben einem OAuth-Konto behalten und mit `config_entry_id` zwischen ihnen wählen.
Auch mehrere Konten gleicher Art sind möglich (zum Beispiel ein kostenloser und ein Pro-Schlüssel); bei mehr als
einem Konto nennst du in Service-Aufrufen das gewünschte mit `config_entry_id`, bei nur einem ist nichts
Zusätzliches nötig.

### Optionen

Unter *Konfigurieren* an der Integration änderst du:

| Option | Standard | Bedeutung |
| --- | --- | --- |
| Standard-Zielsprache | Serversprache | Wird verwendet, wenn ein Aufruf keine Zielsprache nennt |
| Intervall der Verbrauchsabfrage | 30 Min. | Wie oft das Kontingent abgefragt wird (5 bis 1440 Minuten) |
| Größe des Übersetzungs-Caches | 256 | Im Speicher gehaltene Übersetzungen, `0` schaltet den Cache ab |

## Entitäten

Jedes Konto erhält ein Dienstgerät mit diesen Sensoren:

| Sensor | Beschreibung |
| --- | --- |
| Verbrauchte Zeichen | Im aktuellen Abrechnungszeitraum übersetzte Zeichen |
| Zeichenlimit | Kontingent des Zeitraums (Diagnose) |
| Verbleibende Zeichen | Was vom Kontingent übrig ist |
| Kontingent verbraucht | Verbrauchter Anteil in Prozent |
| Ende des Abrechnungszeitraums | Wann die Zähler zurückgesetzt werden (Diagnose, standardmäßig deaktiviert) |

Konten ohne Zeichenobergrenze melden kein Limit, daher bleiben Limit, Rest und Prozent dort `unknown`. Eine
schnelle Dashboard-Karte (die Entity-ID hängt vom Namen deines Kontos ab):

```yaml
type: gauge
entity: sensor.deepl_free_quota_used
name: DeepL-Kontingent
min: 0
max: 100
severity:
  green: 0
  yellow: 70
  red: 90
```

## Es wird nichts gesendet, wenn die Anfrage nicht vollständig möglich ist

Bevor eine Anfrage Home Assistant verlässt, wird sie als Ganzes geprüft. Schlägt eine Prüfung an, gibt es einen
klaren Fehler, der mit *Nothing was sent to DeepL.* endet. Die Prüfungen:

| Prüfung | Abgelehnt, wenn | Benötigt |
| --- | --- | --- |
| Kontingent | die noch benötigten Zeichen (zwischengespeicherte Texte zählen nicht) mehr sind als übrig; ein veralteter Wert wird vorher kostenlos aktualisiert | API-Schlüssel |
| Ziel- und Quellsprache | DeepL sie nicht listet; die Meldung schlägt ähnliche Codes vor | API-Schlüssel |
| Anrede | `more` oder `less` für eine Sprache ohne Anrede verlangt wird (`prefer_more` und `prefer_less` gehen immer) | API-Schlüssel |
| Textgröße | ein einzelner Text für eine Anfrage zu lang ist, egal wie aufgeteilt wird | beide |
| Dateityp | die Endung keine ist, die DeepL übersetzt | API-Schlüssel |
| Markup und Platzhalter | sie verlangt werden, das Konto sie aber nicht schützen kann | OAuth |
| Ausgabedatei | sie existiert (ohne `overwrite`), der Eingabedatei entspricht oder außerhalb der erlaubten Ordner liegt | beide |

Lässt sich eine Prüfung nicht durchführen (etwa weil die Sprachliste von DeepL nicht erreichbar ist), geht die
Anfrage trotzdem raus und DeepL entscheidet. Eine Dateiübersetzung schreibt ihre Ausgabe erst, nachdem jeder
String zurückgekommen ist.

## Services

### `deepl_translator.translate_text`

| Feld | Pflicht | Beschreibung |
| --- | --- | --- |
| `text` | ja | Ein Text oder eine Liste von Texten |
| `target_language` | nein | Zielsprache, zum Beispiel `DE`, `EN-GB`, `PT-BR`. Standard ist die für die Integration eingestellte Sprache |
| `source_language` | nein | Quellsprache. Weglassen, damit DeepL sie erkennt |
| `formality` | nein | `default`, `more`, `less`, `prefer_more`, `prefer_less` |
| `context` | nein | Zusatzkontext, der das Ergebnis verbessert und weder übersetzt noch berechnet wird |
| `glossary_id` | nein | Ein DeepL-Glossar; erfordert `source_language` |
| `tag_handling` | nein | `xml` oder `html`, wenn der Text Markup enthält |
| `config_entry_id` | nein | Das zu verwendende Konto, wenn mehrere eingerichtet sind |

Antwort:

```yaml
text: Guten Morgen!              # die erste Übersetzung, für den üblichen Einzeltext-Fall
translations:
  - text: Guten Morgen!
    detected_source_language: EN
target_language: DE
```

Leere Texte kommen unverändert zurück und werden nicht an DeepL geschickt. Sprachcodes sind großzügig: `de`,
`pt_br` und `PT-BR` funktionieren alle, und `EN` oder `PT` werden zu `EN-US` und `PT-PT`.

### `deepl_translator.translate_document`

| Feld | Pflicht | Beschreibung |
| --- | --- | --- |
| `input_file` | ja | Zu übersetzende Datei. Relative Pfade beginnen im Konfigurationsordner |
| `output_file` | nein | Speicherort des Ergebnisses. Standard ist der Eingabename plus Sprache, z. B. `manual.de.docx` |
| `target_language`, `source_language`, `formality`, `glossary_id`, `config_entry_id` | nein | Wie oben |
| `overwrite` | nein | Ersetzt eine vorhandene Ausgabedatei (Standard: nein, der Aufruf schlägt dann fehl) |
| `timeout` | nein | Wartezeit auf DeepL in Sekunden, 30 bis 3600 (Standard 600) |

Beide Pfade müssen im Konfigurationsordner oder in einem Ordner aus
[`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs)
liegen. Der Aufruf wartet, bis die Übersetzung fertig ist, bei kleinen Dateien Sekunden, bei großen länger.
Starte ihn aus einem Skript (`script.turn_on`), wenn eine Automatisierung nicht darauf warten soll. Die
Antwort enthält `output_file`, `target_language`, `document_id` und `billed_characters`.

```yaml
action: deepl_translator.translate_document
data:
  input_file: /config/www/manual.docx
  output_file: /config/www/manual.de.docx
  target_language: DE
  overwrite: true
```

### `deepl_translator.translate_structure`

Für Konfigurationsdateien, Übersetzungsdateien, Dashboards und andere strukturierte Daten. Reiner Text gehört
zu `translate_text`; dieser Service liest die Struktur und schickt **nur die Textwerte** an DeepL. Danach setzt
er die Übersetzungen wieder ein, sodass das Ergebnis genau wie die Eingabe aussieht. Schlüssel werden nie
übersetzt.

| Feld | Pflicht | Beschreibung |
| --- | --- | --- |
| `input_file` oder `data` | eines davon | Eine JSON- oder YAML-Datei (relative Pfade beginnen im Konfigurationsordner) oder inline übergebene Daten |
| `output_file` | nein | Speicherort einer übersetzten Datei. Standard ist der Eingabename plus Sprache, z. B. `en.de.json` |
| `format` | nein | `auto` (anhand der Dateiendung, Standard), `json` oder `yaml` |
| `only_keys` | nein | Übersetzt nur Werte, die zu diesen Schlüsseln gehören, z. B. `[name, title, message]` |
| `ignore_keys` | nein | Werte dieser Schlüssel werden nie übersetzt |
| `skip_technical_values` | nein | Lässt URLs, Entity-IDs, Icons, Farben, Versionen und Messwerte in Ruhe (Standard: ja) |
| `protect_placeholders` | nein | Lässt `{name}`, `%s`, `${var}` und `{{ Template }}` unverändert (Standard: ja) |
| `dry_run` | nein | Listet auf, was übersetzt würde, samt Zeichenzahl, ohne DeepL zu kontaktieren oder zu schreiben |
| `overwrite` | nein | Ersetzt eine vorhandene Ausgabedatei (Standard: nein) |
| `target_language`, `source_language`, `formality`, `context`, `glossary_id`, `config_entry_id` | nein | Wie bei `translate_text` |

Was der Service mit einer Datei macht:

- **Das Layout bleibt.** JSON und YAML werden nicht aus geparsten Daten neu geschrieben. Es werden nur die
  Positionen der Textwerte gesucht und die Übersetzungen genau dort eingesetzt, sodass Einrückung,
  Schlüsselreihenfolge, Anführungszeichen, Kommentare, Anker und Leerzeilen erhalten bleiben. YAML-Blockskalare
  (`|`, `>`) behalten ihre Einrückung, und eine Übersetzung, die den Typ eines Wertes ändern (`yes`, `1.5`) oder
  die Syntax brechen würde (`: `, `#`), wird automatisch in Anführungszeichen gesetzt. Strings, die DeepL
  unverändert lässt, werden gar nicht angefasst. YAML-Tags wie `!secret` und `!include` bleiben unberührt.
- **Nur Fließtext wird gesendet.** Zahlen, Wahrheitswerte, leere Werte und Strings ohne Buchstaben werden
  übersprungen, mit `skip_technical_values` außerdem URLs, E-Mail-Adressen, Entity-IDs, snake_case-Bezeichner,
  Icons (`mdi:door`), Farben, Versionsnummern und Messwerte (`21.5 °C`).
- **Platzhalter überleben.** Sie werden in ein Tag gepackt, das DeepL ignorieren soll, und danach wieder
  ausgepackt. Enthält ein Text Platzhalter, schaltet das die Anfrage auf den XML-Modus von DeepL um.
- **Schont das Kontingent.** Identische Strings werden nur einmal gesendet und danach aus dem Cache
  beantwortet. Probiere zuerst `dry_run: true` aus, um zu sehen, was eine Datei kosten würde.

> In Konfigurationsdateien sind die meisten Werte technisch (`type: gauge`, `platform: template`). Nutze
> `only_keys` mit den Schlüsseln, die Text enthalten, zum Beispiel `[name, title, message, description]`, und
> prüfe die Liste mit `dry_run`.

```yaml
action: deepl_translator.translate_structure
data:
  input_file: /config/custom_components/my_integration/translations/en.json
  output_file: /config/custom_components/my_integration/translations/de.json
  target_language: DE
  overwrite: true
```

Inline-Daten kommen als Kopie mit derselben Form zurück; ein Dateiaufruf liefert stattdessen den Pfad:

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
# result enthält außerdem translated_strings und skipped_strings
```

Der nächstgelegene Schlüssel entscheidet: Bei den Einträgen einer Liste ist das der Schlüssel, der die Liste
enthält. Ein `dry_run` liefert `strings: [{path, text}]` mit Pfaden wie `views[0].cards[1].title` sowie
`characters` und `skipped_strings`.

### `deepl_translator.get_languages`

Liefert `languages: [{code, name, supports_formality}]` für `type: target` (Standard) oder `type: source`. Die
Antwort wird einen Tag zwischengespeichert.

> Ältere Automatisierungen mit `service:` statt `action:` (Home Assistant vor 2024.8) funktionieren genauso.

## Rezepte

### Eine Benachrichtigung übersetzen

```yaml
automation:
  - alias: Tür offen (übersetzt)
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

Die Automatisierung nutzt die Syntax von Home Assistant 2024.10 und neuer (`triggers:`, `trigger: state`);
ältere Versionen schreiben stattdessen `trigger:` und `platform: state`.

### Aus einer anderen Integration verwenden

Rufe den Service wie jeden anderen auf und frage die Antwort ab. Trage `"after_dependencies": ["deepl_translator"]`
in dein Manifest ein und prüfe, ob der Service existiert, damit deine Integration auch ohne DeepL funktioniert.

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

Fehler kommen als `HomeAssistantError` an (eine abgelehnte Anfrage, etwa wegen einer nicht unterstützten Sprache,
als Unterklasse `ServiceValidationError`), mit der Originalmeldung von DeepL, zum Beispiel zum erschöpften
Kontingent. Für Übersetzungsdateien einer Integration eignet sich `translate_structure`: Aus der `en.json` wird
eine `de.json` mit identischem Aufbau, und Platzhalter wie `{name}` bleiben erhalten.

### Text auf einem Dashboard übersetzen

Templates können keine Services aufrufen, daher übernimmt eine Automatisierung die Arbeit und legt das Ergebnis in
einem `input_text` ab, den die Karte anzeigt. Wiederholte Texte kosten dank Cache nichts.

```yaml
automation:
  - alias: Tipp des Tages übersetzen
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

## DeepL mit KI-Assistenten (MCP)

Alles bisher gilt für Home Assistant. Soll zusätzlich ein KI-Assistent übersetzen, sind die MCP-Server von DeepL
das richtige Werkzeug. Die genauen Menünamen ändern sich zwischen Versionen; schau in die Dokumentation des
Clients, falls etwas anders aussieht.

### Gehosteter DeepL-MCP-Server (empfohlen, nichts zu installieren)

URL: `https://mcp.deepl.com/v1/mcp` (Streamable HTTP). Du meldest dich per OAuth mit deinem DeepL-Konto an, es
gibt also keinen API-Schlüssel zu verwalten. Der Server nutzt den Tarif des Kontos und zeigt nur die Werkzeuge,
die der Tarif erlaubt.

| Client | So geht es |
| --- | --- |
| Claude (App) | *Einstellungen > Konnektoren > Benutzerdefinierten Konnektor hinzufügen*, URL einfügen, anmelden |
| Claude Code | `claude mcp add --transport http deepl https://mcp.deepl.com/v1/mcp`, danach mit `/mcp` anmelden |
| ChatGPT | Entwicklermodus aktivieren, einen benutzerdefinierten Konnektor/eine App mit der URL hinzufügen und anmelden |
| Codex | `codex mcp add deepl --url https://mcp.deepl.com/v1/mcp`, danach `codex mcp login deepl` |
| OpenClaw | Den Server unter `mcp.servers` eintragen (siehe unten), danach `openclaw mcp login deepl` |

Codex kann ihn auch aus `~/.codex/config.toml` lesen:

```toml
[mcp_servers.deepl]
url = "https://mcp.deepl.com/v1/mcp"
```

OpenClaw gemäß seiner Konfigurationsreferenz (prüfe mit `openclaw config schema`):

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

### Der selbst gehostete `deepl-mcp-server` (API-Schlüssel, läuft lokal)

[DeepL/deepl-mcp-server](https://github.com/DeepL/deepl-mcp-server) nutzt deinen API-Schlüssel und spricht
stdio, eignet sich also für Assistenten, die lokale Werkzeuge starten. Er braucht Node.js 18 oder neuer.

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

Gegenüber dem gehosteten Server braucht er einen lokalen Node.js-Prozess und bietet weniger Werkzeuge
(Übersetzen, Umformulieren und lesende Abfragen). Wähle ihn nur, wenn die OAuth-Anmeldung keine Option ist.

### Einen Assistenten diese Integration über Home Assistant nutzen lassen

Ein Assistent kann DeepL auch über dein Home Assistant erreichen. Das zählt gegen dasselbe Kontingent, das die
Sensoren anzeigen:

1. Verpacke den Service in ein Skript und gib es für Assist frei (*Einstellungen > Sprachassistenten > Freigeben*):

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

2. Aktiviere die Integration **Model Context Protocol Server** in Home Assistant und verbinde deinen Assistenten mit
   `http://<dein-home-assistant>:8123/api/mcp` (die URL steht unter *Einstellungen > System > KI*). Die Werkzeuge von
   Assist, einschließlich freigegebener Skripte, stehen ihm dann zur Verfügung, und dasselbe Skript bedient auch die
   Konversations-Agenten von Assist.

## Gut zu wissen

- Logo und Icon sind eigene Grafiken für dieses Projekt: ein Haus und zwei Sprechblasen. Sie ahmen weder das Logo von
  DeepL noch das von Home Assistant nach. Dies ist eine inoffizielle Integration, nicht von DeepL SE oder dem
  Home-Assistant-Projekt erstellt, empfohlen oder unterstützt. DeepL ist eine Marke der DeepL SE und Home Assistant
  eine Marke der Open Home Foundation; sie werden hier nur genannt, um zu sagen, womit die Integration arbeitet.

- Kostenlose Konten übersetzen bis zu 500.000 Zeichen pro Monat. Ist das Kontingent aufgebraucht, antwortet DeepL
  mit `456`; der Service schlägt dann mit einer klaren Meldung fehl, statt es erneut zu versuchen.
- Das Feld `context` wird nicht berechnet. Dokumente werden nach den Regeln von DeepL berechnet, siehe
  `billed_characters` in der Antwort.
- Lehnt DeepL den Schlüssel ab (zum Beispiel nach einer Rotation), zeigt Home Assistant einen
  Reauthentifizierungs-Hinweis, in dem du den neuen Schlüssel einträgst; nichts muss neu installiert werden.
- Lade für einen Fehlerbericht die *Diagnose* von der Integrationsseite herunter; der API-Schlüssel ist darin entfernt.

## Entwicklung

Die Tests in `.github/tests` laufen überall mit `python -m unittest discover -s .github/tests`. Die in
`.github/ha_tests` laufen in echten Home-Assistant-Versionen ab dem Minimum in `hacs.json`; den Matrix-Runner
findest du in der [Workflow-Engine](https://github.com/seb5594/hass-workflows).

## Lizenz

Veröffentlicht unter der [MIT-Lizenz](LICENSE).

## Optionaler Custom Integration Translator

Ab Home Assistant 2023.7 erkennt ein eingerichtetes DeepL-Konto den installierten [Custom Integration Translator](https://github.com/seb5594/hass-custom_integrations_translator-integration) ab Version 2026.11.05.4. Nach einer HACS-/Marketplace-Installation oder einem Home-Assistant-Neustart bietet eine **Entdeckt**-Kachel unter **Einstellungen → Geräte & Dienste** die Einrichtung an. Du kannst den Vorschlag einrichten oder ignorieren. Der Translator wird niemals automatisch heruntergeladen. Die Erkennung reagiert auf Installationsereignisse und den Start, ohne regelmäßige Abfragen oder DeepL-Anfragen. Manuell kopierte Dateien benötigen einen Home-Assistant-Neustart. 

Unter **Konfigurieren → Custom Integration Translator entdecken** schaltest du den Einrichtungsvorschlag für dieses Konto aus. Deaktiviere ihn bei allen DeepL-Konten, um die Erkennung vollständig abzuschalten. Noch offene Bestätigungskacheln werden entfernt; die manuelle Einrichtung, aktive Translator-Instanzen und bereits geöffnete Kontoauswahlen bleiben verfügbar.
