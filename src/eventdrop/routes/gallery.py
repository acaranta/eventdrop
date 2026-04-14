# Gallery routes stub — full implementation pending.

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["gallery"])


@router.get("/gallery/{event_id}", response_class=HTMLResponse)
async def gallery_page(request: Request, event_id: str):
    """Gallery page placeholder."""
    return HTMLResponse(f"<h1>Gallery for event {event_id} — coming soon</h1>")
