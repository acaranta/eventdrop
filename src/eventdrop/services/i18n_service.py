import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = ["en", "fr", "de", "es", "it"]
LANG_FLAGS = {"en": "🇬🇧", "fr": "🇫🇷", "de": "🇩🇪", "es": "🇪🇸", "it": "🇮🇹"}

_I18N_DIR = Path(__file__).parent.parent / "i18n"


@lru_cache(maxsize=10)
def _load(lang: str) -> dict:
    path = _I18N_DIR / f"{lang}.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"Translation file not found: {path}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {path}: {e}")
        return {}


def _lookup(data: dict, key: str, fallback: dict | None = None) -> str:
    """Resolve a dot-separated key in a nested dict.  Falls back to English, then to the key itself."""
    parts = key.split(".")
    node = data
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            node = None
            break
    if isinstance(node, str):
        return node
    # Fall back to English if not found
    if fallback is not None:
        node = fallback
        for part in parts:
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        if isinstance(node, str):
            return node
    # Last resort: return the key itself
    return key


def detect_lang(request) -> str:
    """Detect language from cookie, then Accept-Language header, then default to English."""
    lang = request.cookies.get("lang")
    if lang and lang in SUPPORTED_LANGS:
        return lang
    accept = request.headers.get("accept-language", "")
    for item in accept.split(","):
        code = item.split(";")[0].strip()[:2].lower()
        if code in SUPPORTED_LANGS:
            return code
    return "en"


def get_translator(lang: str) -> Callable[[str], str]:
    """Return a translation function for the given language."""
    translations = _load(lang)
    en_fallback = _load("en") if lang != "en" else None

    def t(key: str) -> str:
        return _lookup(translations, key, en_fallback)

    return t
