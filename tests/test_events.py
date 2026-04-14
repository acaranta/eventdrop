"""Tests for event management routes."""
import pytest
from httpx import AsyncClient

from eventdrop.database.models import User, Event


async def _login(client: AsyncClient, username: str, password: str):
    """Helper to log in a user and return the response."""
    return await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


async def _logout(client: AsyncClient):
    """Helper to log out the current user."""
    await client.get("/auth/logout", follow_redirects=True)


@pytest.mark.asyncio
async def test_unauthenticated_user_redirected_from_events(test_client: AsyncClient):
    """GET /events/ without a session should redirect to login."""
    response = await test_client.get("/events/", follow_redirects=False)
    assert response.status_code in (302, 303)
    location = response.headers.get("location", "")
    assert "/auth/login" in location or "/login" in location


@pytest.mark.asyncio
async def test_authenticated_user_can_access_events(
    test_client: AsyncClient, test_user: User
):
    """GET /events/ as a logged-in user should return 200."""
    await _login(test_client, "testuser", "password123")
    response = await test_client.get("/events/")
    assert response.status_code == 200
    await _logout(test_client)


@pytest.mark.asyncio
async def test_authenticated_user_can_create_event(
    test_client: AsyncClient, test_user: User
):
    """POST /events/create as a logged-in user should create an event."""
    await _login(test_client, "testuser", "password123")
    response = await test_client.post(
        "/events/create",
        data={
            "name": "My New Test Event",
            "description": "Created during test",
            "is_gallery_public": "false",
            "allow_public_download": "false",
        },
        follow_redirects=False,
    )
    # Should redirect to the edit page for the newly created event
    assert response.status_code in (302, 303)
    location = response.headers.get("location", "")
    assert "/events/" in location and "/edit" in location
    await _logout(test_client)


@pytest.mark.asyncio
async def test_event_create_page_accessible(
    test_client: AsyncClient, test_user: User
):
    """GET /events/create as a logged-in user should return 200."""
    await _login(test_client, "testuser", "password123")
    response = await test_client.get("/events/create")
    assert response.status_code == 200
    await _logout(test_client)


@pytest.mark.asyncio
async def test_event_owner_can_edit_event(
    test_client: AsyncClient, test_user: User, test_event: Event
):
    """POST /events/{id}/edit as owner should update the event."""
    await _login(test_client, "testuser", "password123")
    response = await test_client.post(
        f"/events/{test_event.id}/edit",
        data={
            "name": "Updated Event Name",
            "description": "Updated description",
            "is_gallery_public": "false",
            "allow_public_download": "false",
            "is_active": "true",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    await _logout(test_client)


@pytest.mark.asyncio
async def test_non_owner_cannot_edit_event(
    test_client: AsyncClient, test_admin: User, test_event: Event
):
    """POST /events/{id}/edit by a non-owner non-admin should return 403."""
    # Create and login as a different non-admin user
    import uuid
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from eventdrop.database.models import Base, User as UserModel
    from eventdrop.auth.passwords import hash_password

    # Sign up a second regular user
    await test_client.post(
        "/auth/signup",
        data={
            "username": "anotherusr",
            "email": "another2@example.com",
            "password": "anotherpass",
            "confirm_password": "anotherpass",
        },
        follow_redirects=True,
    )
    await _logout(test_client)

    # Log in as that other user
    await _login(test_client, "anotherusr", "anotherpass")
    response = await test_client.post(
        f"/events/{test_event.id}/edit",
        data={
            "name": "Hacked Name",
            "description": "Not allowed",
            "is_gallery_public": "false",
            "allow_public_download": "false",
            "is_active": "true",
        },
        follow_redirects=False,
    )
    assert response.status_code == 403
    await _logout(test_client)


@pytest.mark.asyncio
async def test_admin_can_edit_any_event(
    test_client: AsyncClient, test_admin: User, test_event: Event
):
    """POST /events/{id}/edit by admin should succeed even if not the owner."""
    await _login(test_client, "testadmin", "adminpass123")
    response = await test_client.post(
        f"/events/{test_event.id}/edit",
        data={
            "name": "Admin-edited Name",
            "description": "Edited by admin",
            "is_gallery_public": "false",
            "allow_public_download": "false",
            "is_active": "true",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    await _logout(test_client)


@pytest.mark.asyncio
async def test_event_edit_page_returns_200_for_owner(
    test_client: AsyncClient, test_user: User, test_event: Event
):
    """GET /events/{id}/edit as owner should return 200."""
    await _login(test_client, "testuser", "password123")
    response = await test_client.get(f"/events/{test_event.id}/edit")
    assert response.status_code == 200
    await _logout(test_client)


@pytest.mark.asyncio
async def test_qr_code_endpoint_returns_png(
    test_client: AsyncClient, test_event: Event
):
    """GET /events/{id}/qr.png should return a PNG image."""
    response = await test_client.get(f"/events/{test_event.id}/qr.png")
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("image/png")


@pytest.mark.asyncio
async def test_qr_code_for_nonexistent_event_returns_404(test_client: AsyncClient):
    """GET /events/missing1/qr.png should return 404."""
    response = await test_client.get("/events/missing1/qr.png")
    assert response.status_code == 404
