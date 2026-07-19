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
async def test_upload_page_shows_closed_notice_when_uploads_disabled(
    test_client: AsyncClient, db_session, test_user: User
):
    """Uploads disabled + private gallery → 200 with a closed notice, no gallery link."""
    from eventdrop.database.models import Event as EventModel

    closed_event = EventModel(
        id="closedev1",
        name="Closed Event",
        owner_id=test_user.id,
        uploads_enabled=False,
        is_gallery_public=False,
    )
    db_session.add(closed_event)
    await db_session.commit()

    response = await test_client.get("/e/closedev1/")
    assert response.status_code == 200
    assert "Uploads are closed" in response.text
    # Private gallery + anonymous visitor → no link offered
    assert "/e/closedev1/gallery/" not in response.text

    await db_session.delete(closed_event)
    await db_session.commit()


@pytest.mark.asyncio
async def test_upload_page_offers_gallery_link_when_gallery_public(
    test_client: AsyncClient, db_session, test_user: User
):
    """Uploads disabled + public gallery → closed notice that still links the gallery."""
    from eventdrop.database.models import Event as EventModel

    closed_event = EventModel(
        id="closedev2",
        name="Closed But Public",
        owner_id=test_user.id,
        uploads_enabled=False,
        is_gallery_public=True,
    )
    db_session.add(closed_event)
    await db_session.commit()

    response = await test_client.get("/e/closedev2/")
    assert response.status_code == 200
    assert "Uploads are closed" in response.text
    assert "/e/closedev2/gallery/" in response.text

    await db_session.delete(closed_event)
    await db_session.commit()


@pytest.mark.asyncio
async def test_closed_page_offers_gallery_link_to_owner_when_private(
    test_client: AsyncClient, db_session, test_user: User
):
    """Owners can reach a private gallery, so they get the link even when it isn't public."""
    from eventdrop.database.models import Event as EventModel

    closed_event = EventModel(
        id="closedev4",
        name="Closed Private",
        owner_id=test_user.id,
        uploads_enabled=False,
        is_gallery_public=False,
    )
    db_session.add(closed_event)
    await db_session.commit()

    await test_client.post(
        "/auth/login",
        data={"username": "testuser", "password": "password123"},
        follow_redirects=True,
    )
    response = await test_client.get("/e/closedev4/")
    assert response.status_code == 200
    assert "/e/closedev4/gallery/" in response.text
    await test_client.get("/auth/logout", follow_redirects=True)

    await db_session.delete(closed_event)
    await db_session.commit()


@pytest.mark.asyncio
async def test_upload_rejected_when_uploads_disabled(
    test_client: AsyncClient, db_session, test_user: User
):
    """The closed landing page must not become a way around the upload guard."""
    from eventdrop.database.models import Event as EventModel

    closed_event = EventModel(
        id="closedev3",
        name="Closed Event",
        owner_id=test_user.id,
        uploads_enabled=False,
    )
    db_session.add(closed_event)
    await db_session.commit()

    response = await test_client.post(
        "/api/e/closedev3/upload",
        files={"file": ("x.png", io.BytesIO(b"fake"), "image/png")},
    )
    assert response.status_code == 404

    await db_session.delete(closed_event)
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
