"""Constants for the DeepL Translator integration."""

from __future__ import annotations

DOMAIN = "deepl_translator"

# Config entry data and options
CONF_DEFAULT_TARGET_LANGUAGE = "default_target_language"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_CACHE_SIZE = "cache_size"

# OAuth sign-in (DeepL's hosted MCP server)
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_AUTHORIZE_URL = "authorize_url"
CONF_TOKEN_URL = "token_url"
MCP_URL = "https://mcp.deepl.com/v1/mcp"
OAUTH_SCOPE = "offline_access"
OAUTH_CLIENT_NAME = "Home Assistant (DeepL Translator)"
OAUTH_TIMEOUT = 30

# Usage polling (minutes). The quota changes slowly, so the default is relaxed.
DEFAULT_UPDATE_INTERVAL = 30
MIN_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 1440

# Translation cache (number of entries, 0 disables it)
DEFAULT_CACHE_SIZE = 256
MAX_CACHE_SIZE = 5000
CACHE_MAX_TEXT_LENGTH = 5000

# After a billed request the usage sensors are refreshed once things calm down.
USAGE_REFRESH_COOLDOWN = 30.0

# DeepL REST API
API_URL_FREE = "https://api-free.deepl.com"
API_URL_PRO = "https://api.deepl.com"
FREE_KEY_SUFFIX = ":fx"
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY = 30
MAX_TEXTS_PER_REQUEST = 50
MAX_REQUEST_BYTES = 120_000
LANGUAGES_CACHE_SECONDS = 24 * 3600

# A character limit this large means "no limit" (Pro accounts without a cap).
UNLIMITED_CHARACTER_LIMIT = 10**12

# Documents
SUPPORTED_DOCUMENT_EXTENSIONS = frozenset(
    {
        ".docx", ".pptx", ".xlsx", ".xlsm", ".pdf", ".htm", ".html", ".txt", ".md", ".markdown",
        ".xlf", ".xliff", ".srt", ".vtt", ".idml", ".mif", ".xml", ".json", ".yaml", ".yml",
        ".properties", ".strings", ".resx", ".dita", ".zip", ".odt", ".rtf", ".jpg", ".jpeg", ".png",
    }
)
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
DEFAULT_DOCUMENT_TIMEOUT = 600
MIN_DOCUMENT_TIMEOUT = 30
MAX_DOCUMENT_TIMEOUT = 3600
DOCUMENT_POLL_MIN_DELAY = 2
DOCUMENT_POLL_MAX_DELAY = 10

# Service names
SERVICE_TRANSLATE_TEXT = "translate_text"
SERVICE_TRANSLATE_DOCUMENT = "translate_document"
SERVICE_TRANSLATE_STRUCTURE = "translate_structure"
SERVICE_GET_LANGUAGES = "get_languages"

# Service fields
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_TEXT = "text"
ATTR_TARGET_LANGUAGE = "target_language"
ATTR_SOURCE_LANGUAGE = "source_language"
ATTR_FORMALITY = "formality"
ATTR_CONTEXT = "context"
ATTR_GLOSSARY_ID = "glossary_id"
ATTR_TAG_HANDLING = "tag_handling"
ATTR_INPUT_FILE = "input_file"
ATTR_OUTPUT_FILE = "output_file"
ATTR_OVERWRITE = "overwrite"
ATTR_TIMEOUT = "timeout"
ATTR_LANGUAGE_TYPE = "type"
ATTR_DATA = "data"
ATTR_FORMAT = "format"
ATTR_ONLY_KEYS = "only_keys"
ATTR_IGNORE_KEYS = "ignore_keys"
ATTR_SKIP_TECHNICAL_VALUES = "skip_technical_values"
ATTR_PROTECT_PLACEHOLDERS = "protect_placeholders"
ATTR_DRY_RUN = "dry_run"

FORMALITY_VALUES = ("default", "more", "less", "prefer_more", "prefer_less")
TAG_HANDLING_VALUES = ("none", "xml", "html")
LANGUAGE_TYPES = ("target", "source")
STRUCTURE_FORMATS = ("auto", "json", "yaml")
STRUCTURE_SUFFIXES = {".json": "json", ".yaml": "yaml", ".yml": "yaml"}
