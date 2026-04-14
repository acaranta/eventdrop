# REST API routes stub — full implementation pending.

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
async def health():
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})
