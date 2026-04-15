from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from eventdrop.services.i18n_service import SUPPORTED_LANGS

router = APIRouter(tags=["lang"])


@router.get("/set-lang")
async def set_lang(lang: str = "en", next: str = "/"):
    if lang not in SUPPORTED_LANGS:
        lang = "en"
    # Sanitize next to prevent open redirect — only allow relative paths
    if not next.startswith("/"):
        next = "/"
    response = RedirectResponse(url=next, status_code=302)
    response.set_cookie("lang", lang, max_age=365 * 24 * 3600, samesite="lax", httponly=False)
    return response
