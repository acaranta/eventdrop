from eventdrop.config import settings
from eventdrop.services.i18n_service import detect_lang, get_translator, SUPPORTED_LANGS, LANG_FLAGS


def build_ctx(request, user=None, **kwargs) -> dict:
    """Build a unified template context with i18n, flash, user and settings."""
    lang = detect_lang(request)
    flash = request.session.pop("flash", None)
    return {
        "user": user,
        "settings": settings,
        "flash": flash,
        "lang": lang,
        "t": get_translator(lang),
        "supported_langs": SUPPORTED_LANGS,
        "lang_flags": LANG_FLAGS,
        **kwargs,
    }
