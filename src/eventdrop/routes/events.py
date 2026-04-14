# Events routes stub — full implementation pending.

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/", response_class=HTMLResponse)
async def events_index(request: Request):
    """Events list placeholder."""
    return HTMLResponse("<h1>Events — coming soon</h1>")
