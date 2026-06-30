"""Helpers for authenticating the TestClient against session-based auth.

The TestClient (httpx) keeps a cookie jar, so once we register/login the session
cookie rides along on every subsequent request from the same client.
"""

from app.config import settings

API = settings.api_v1_prefix
DEFAULT_EMAIL = "tester@example.com"
DEFAULT_PASSWORD = "password123"


def login(tc, email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD):
    """Register (or log in if already registered) so `tc` carries a session."""
    res = tc.post(f"{API}/auth/register", json={"email": email, "password": password})
    if res.status_code == 409:
        res = tc.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert res.status_code in (200, 201), res.text
    return res


def create_project(tc, name: str = "Test Project") -> dict:
    """Create a project for the logged-in user; returns the JSON (incl. api_key)."""
    res = tc.post(f"{API}/projects", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()
