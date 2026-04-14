"""Tests for the upload functionality."""
import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

from eventdrop.database.models import User, Event


@pytest.mark.asyncio
async def test_upload_page_returns_200_for_active_event(
    test_client: AsyncClient, test_event: Event
):
    """GET /e/{event_id}/ should return 200 for an existing, active event."""
    response = await test_client.get(f"/e/{test_event.id}/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_upload_page_returns_404_for_nonexistent_event(test_client: AsyncClient):
    """GET /e/notfound/ should return 404 when event does not exist."""
    response = await test_client.get("/e/notfound/")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_page_returns_404_for_inactive_event(
    test_client: AsyncClient, db_session, test_user: User
):
    """GET /e/{event_id}/ for an inactive event should return 404."""
    from eventdrop.database.models import Event as EventModel

    inactive_event = EventModel(
        id="inactev1",
        name="Inactive Event",
        owner_id=test_user.id,
        is_active=False,
    )
    db_session.add(inactive_event)
    await db_session.commit()

    response = await test_client.get("/e/inactev1/")
    assert response.status_code == 404

    await db_session.delete(inactive_event)
    await db_session.commit()


@pytest.mark.asyncio
async def test_file_upload_without_email_returns_400(
    test_client: AsyncClient, test_event: Event
):
    """POST /api/e/{event_id}/upload without an email session returns 400."""
    # No cookie, no logged-in user → no email available
    small_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = await test_client.post(
        f"/api/e/{test_event.id}/upload",
        files={"file": ("test.png", io.BytesIO(small_png), "image/png")},
    )
    assert response.status_code == 400
    body = response.json()
    assert "email" in body.get("detail", "").lower()


@pytest.mark.asyncio
async def test_file_upload_for_nonexistent_event_returns_404(test_client: AsyncClient):
    """POST /api/e/missing1/upload should return 404."""
    small_png = b"\x89PNG\r\n\x1a\n"
    response = await test_client.post(
        "/api/e/missing1/upload",
        files={"file": ("test.png", io.BytesIO(small_png), "image/png")},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_file_upload_too_large_returns_413(
    test_client: AsyncClient, test_event: Event
):
    """POST /api/e/{event_id}/upload with an oversized file should return 413."""
    from eventdrop.config import settings

    # First set an uploader email cookie
    await test_client.post(
        f"/e/{test_event.id}/set-email",
        data={"email": "uploader@example.com"},
        follow_redirects=False,
    )

    # Create a fake file that exceeds the configured limit
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    oversized_data = b"X" * (max_bytes + 1)

    with patch("magic.from_buffer", return_value="image/jpeg"):
        response = await test_client.post(
            f"/api/e/{test_event.id}/upload",
            files={"file": ("big.jpg", io.BytesIO(oversized_data), "image/jpeg")},
        )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_set_email_cookie_redirects(
    test_client: AsyncClient, test_event: Event
):
    """POST /e/{event_id}/set-email should set a cookie and redirect."""
    response = await test_client.post(
        f"/e/{test_event.id}/set-email",
        data={"email": "cookie_user@example.com"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    # Cookie should be set
    assert "uploader_token" in response.cookies or any(
        "uploader_token" in c for c in response.headers.get("set-cookie", "")
    )


@pytest.mark.asyncio
async def test_clear_email_cookie_redirects(
    test_client: AsyncClient, test_event: Event
):
    """POST /e/{event_id}/clear-email should delete cookie and redirect."""
    response = await test_client.post(
        f"/e/{test_event.id}/clear-email",
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
