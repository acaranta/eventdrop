"""Tests for authentication routes: login, signup, logout."""
import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from eventdrop.main import app
from eventdrop.database.session import get_db
from eventdrop.database.models import Base, User
from eventdrop.auth.passwords import hash_password


@pytest.mark.asyncio
async def test_login_page_returns_200(test_client: AsyncClient):
    """GET /auth/login should return a 200 response."""
    response = await test_client.get("/auth/login")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_signup_page_returns_200(test_client: AsyncClient):
    """GET /auth/signup should return a 200 response."""
    response = await test_client.get("/auth/signup")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_signup_creates_user_and_redirects(test_client: AsyncClient):
    """POST /auth/signup with valid data should create user and redirect."""
    response = await test_client.post(
        "/auth/signup",
        data={
            "username": "newuser_signup",
            "email": "newuser@example.com",
            "password": "securepass",
            "confirm_password": "securepass",
        },
        follow_redirects=False,
    )
    # Should redirect after successful signup
    assert response.status_code in (302, 303)
    assert "/events/" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_login_with_valid_credentials_redirects(
    test_client: AsyncClient, test_user: User
):
    """POST /auth/login with correct credentials should redirect to /events/."""
    response = await test_client.post(
        "/auth/login",
        data={"username": "testuser", "password": "password123"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "/events/" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_error(
    test_client: AsyncClient, test_user: User
):
    """POST /auth/login with wrong password should return 401 with error message."""
    response = await test_client.post(
        "/auth/login",
        data={"username": "testuser", "password": "wrongpassword"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert b"Invalid" in response.content or b"invalid" in response.content


@pytest.mark.asyncio
async def test_login_with_nonexistent_user_returns_error(test_client: AsyncClient):
    """POST /auth/login with unknown username should return 401."""
    response = await test_client.post(
        "/auth/login",
        data={"username": "doesnotexist", "password": "somepassword"},
        follow_redirects=False,
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_session_and_redirects(test_client: AsyncClient):
    """GET /auth/logout should clear the session and redirect."""
    # First log in to establish a session
    await test_client.post(
        "/auth/login",
        data={"username": "testuser", "password": "password123"},
        follow_redirects=True,
    )
    response = await test_client.get("/auth/logout", follow_redirects=False)
    assert response.status_code in (302, 303)
    # After logout, accessing /events/ should redirect back to login
    events_response = await test_client.get("/events/", follow_redirects=False)
    assert events_response.status_code in (302, 303)


@pytest.mark.asyncio
async def test_signup_with_short_password_fails(test_client: AsyncClient):
    """POST /auth/signup with a password shorter than 8 chars should fail."""
    response = await test_client.post(
        "/auth/signup",
        data={
            "username": "shortpassuser",
            "email": "short@example.com",
            "password": "abc",
            "confirm_password": "abc",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert b"8" in response.content or b"characters" in response.content


@pytest.mark.asyncio
async def test_signup_with_duplicate_username_fails(
    test_client: AsyncClient, test_user: User
):
    """POST /auth/signup with an already-taken username should return 400."""
    response = await test_client.post(
        "/auth/signup",
        data={
            "username": "testuser",  # already exists from test_user fixture
            "email": "another@example.com",
            "password": "validpassword",
            "confirm_password": "validpassword",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert b"taken" in response.content or b"already" in response.content


@pytest.mark.asyncio
async def test_signup_password_mismatch_fails(test_client: AsyncClient):
    """POST /auth/signup with non-matching passwords should return 400."""
    response = await test_client.post(
        "/auth/signup",
        data={
            "username": "mismatchuser",
            "email": "mismatch@example.com",
            "password": "validpassword",
            "confirm_password": "differentpassword",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
