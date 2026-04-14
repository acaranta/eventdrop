# Admin routes stub — full implementation pending.

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/", response_class=HTMLResponse)
async def admin_index(request: Request):
    """Admin dashboard placeholder."""
    return HTMLResponse("<h1>Admin Dashboard — coming soon</h1>")
