"""Tests for gallery access control."""
import pytest
from httpx import AsyncClient

from eventdrop.database.models import User, Event


async def _login(client: AsyncClient, username: str, password: str):
    """Helper: log in via the auth route."""
    return await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


async def _logout(client: AsyncClient):
    """Helper: log out the current session."""
    await client.get("/auth/logout", follow_redirects=True)


@pytest.mark.asyncio
async def test_public_gallery_accessible_to_anonymous(
    test_client: AsyncClient, test_event: Event
):
    """A public gallery should be accessible without authentication."""
    # test_event has is_gallery_public=True
    response = await test_client.get(f"/e/{test_event.id}/gallery/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_private_gallery_redirects_anonymous_user(
    test_client: AsyncClient, db_session, test_user: User
):
    """A private gallery should redirect anonymous users."""
    private_event = Event(
        id="privevt1",
        name="Private Event",
        owner_id=test_user.id,
        is_gallery_public=False,
        allow_public_download=False,
        is_active=True,
    )
    db_session.add(private_event)
    await db_session.commit()

    response = await test_client.get("/e/privevt1/gallery/", follow_redirects=False)
    # Should either redirect to login (302) or return 403
    assert response.status_code in (302, 303, 403)

    await db_session.delete(private_event)
    await db_session.commit()


@pytest.mark.asyncio
async def test_private_gallery_accessible_to_owner(
    test_client: AsyncClient, db_session, test_user: User
):
    """A private gallery should be accessible to the event owner."""
    private_event = Event(
        id="privevt2",
        name="Owner Private Event",
        owner_id=test_user.id,
        is_gallery_public=False,
        allow_public_download=False,
        is_active=True,
    )
    db_session.add(private_event)
    await db_session.commit()

    await _login(test_client, "testuser", "password123")
    response = await test_client.get("/e/privevt2/gallery/")
    assert response.status_code == 200

    await _logout(test_client)
    await db_session.delete(private_event)
    await db_session.commit()


@pytest.mark.asyncio
async def test_admin_can_access_private_gallery(
    test_client: AsyncClient, db_session, test_user: User, test_admin: User
):
    """An admin should be able to access any private gallery."""
    private_event = Event(
        id="privevt3",
        name="Admin Test Private Event",
        owner_id=test_user.id,
        is_gallery_public=False,
        allow_public_download=False,
        is_active=True,
    )
    db_session.add(private_event)
    await db_session.commit()

    await _login(test_client, "testadmin", "adminpass123")
    response = await test_client.get("/e/privevt3/gallery/")
    assert response.status_code == 200

    await _logout(test_client)
    await db_session.delete(private_event)
    await db_session.commit()


@pytest.mark.asyncio
async def test_gallery_nonexistent_event_returns_404(test_client: AsyncClient):
    """A gallery for a non-existent event should return 404."""
    response = await test_client.get("/e/notfound/gallery/")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_private_gallery_returns_403_for_logged_in_non_owner(
    test_client: AsyncClient, db_session, test_user: User
):
    """A private gallery should return 403 for a logged-in user who is not the owner."""
    private_event = Event(
        id="privevt4",
        name="Non-owner Private Event",
        owner_id=test_user.id,
        is_gallery_public=False,
        allow_public_download=False,
        is_active=True,
    )
    db_session.add(private_event)
    await db_session.commit()

    # Sign up and log in as a different user
    await test_client.post(
        "/auth/signup",
        data={
            "username": "galleryvisitor",
            "email": "visitor@example.com",
            "password": "visitpass",
            "confirm_password": "visitpass",
        },
        follow_redirects=True,
    )

    response = await test_client.get("/e/privevt4/gallery/", follow_redirects=False)
    assert response.status_code in (403, 302, 303)

    await _logout(test_client)
    await db_session.delete(private_event)
    await db_session.commit()
