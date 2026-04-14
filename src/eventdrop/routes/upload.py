# Upload routes stub — full implementation pending.

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["upload"])


@router.get("/upload/{event_id}", response_class=HTMLResponse)
async def upload_page(request: Request, event_id: str):
    """Upload page placeholder."""
    return HTMLResponse(f"<h1>Upload to event {event_id} — coming soon</h1>")
