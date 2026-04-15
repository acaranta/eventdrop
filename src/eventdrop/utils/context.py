import time

from eventdrop.config import settings
from eventdrop.services.i18n_service import detect_lang, get_translator, SUPPORTED_LANGS, LANG_FLAGS

# Simple TTL cache — avoids a DB round-trip on every request
_reg_cache: dict = {"value": True, "ts": 0.0}
_REG_TTL = 60.0  # seconds


async def _get_allow_registration() -> bool:
    if time.monotonic() - _reg_cache["ts"] < _REG_TTL:
        return _reg_cache["value"]
    from eventdrop.database.engine import AsyncSessionLocal
    from eventdrop.services.settings_service import get_setting
    async with AsyncSessionLocal() as session:
        val = (await get_setting(session, "allow_registration")) == "true"
    _reg_cache["value"] = val
    _reg_cache["ts"] = time.monotonic()
    return val


def invalidate_registration_cache() -> None:
    """Call this when admin saves settings so the next request re-reads the DB."""
    _reg_cache["ts"] = 0.0


async def build_ctx(request, user=None, **kwargs) -> dict:
    """Build a unified template context with i18n, flash, user, settings and registration flag."""
    lang = detect_lang(request)
    flash = request.session.pop("flash", None)
    allow_registration = await _get_allow_registration()
    return {
        "user": user,
        "settings": settings,
        "flash": flash,
        "lang": lang,
        "t": get_translator(lang),
        "supported_langs": SUPPORTED_LANGS,
        "lang_flags": LANG_FLAGS,
        "allow_registration": allow_registration,
        **kwargs,
    }
