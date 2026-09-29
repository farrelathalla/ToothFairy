from app.models.user import Role
from app.services import accounts


def _mk(db, email="doc@x.io", pw="doctor123", role=Role.doctor, active=True):
    u = accounts.create_user(db, email=email, name="Doc", password=pw, role=role)
    if not active:
        accounts.update_user(db, u.id, is_active=False)
    return u


def test_login_success_sets_cookie_and_returns_user(client, db):
    _mk(db)
    r = client.post("/auth/login", json={"email": "doc@x.io", "password": "doctor123"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["user"]["email"] == "doc@x.io"
    assert body["user"]["role"] == "doctor"
    assert "access_token" in r.cookies


def test_login_wrong_password_401(client, db):
    _mk(db)
    r = client.post("/auth/login", json={"email": "doc@x.io", "password": "nope"})
    assert r.status_code == 401


def test_login_unknown_email_401(client):
    r = client.post("/auth/login", json={"email": "ghost@x.io", "password": "x"})
    assert r.status_code == 401


def test_login_inactive_403(client, db):
    _mk(db, active=False)
    r = client.post("/auth/login", json={"email": "doc@x.io", "password": "doctor123"})
    assert r.status_code == 403


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401


def test_me_with_bearer_and_cookie(client, db):
    _mk(db)
    login = client.post("/auth/login", json={"email": "doc@x.io", "password": "doctor123"})
    token = login.json()["token"]

    # bearer header
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "doc@x.io"

    # cookie (TestClient stored it from login)
    r2 = client.get("/auth/me")
    assert r2.status_code == 200


def test_logout_clears_cookie(client, db):
    _mk(db)
    client.post("/auth/login", json={"email": "doc@x.io", "password": "doctor123"})
    r = client.post("/auth/logout")
    assert r.status_code == 200
    # after logout the cookie is cleared → /me unauthorized
    client.cookies.clear()
    assert client.get("/auth/me").status_code == 401
