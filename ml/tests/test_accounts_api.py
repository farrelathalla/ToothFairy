from app.models.user import Role
from app.security import create_token
from app.services import accounts


def _token(db, role=Role.admin, email=None):
    email = email or f"{role.value}@x.io"
    u = accounts.create_user(db, email=email, name=role.value, password="secret1", role=role)
    return create_token(u)


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_unauthenticated_gets_401(client):
    assert client.get("/accounts").status_code == 401


def test_doctor_forbidden_403(client, db):
    tok = _token(db, Role.doctor)
    assert client.get("/accounts", headers=_auth(tok)).status_code == 403
    r = client.post(
        "/accounts",
        headers=_auth(tok),
        json={"email": "n@x.io", "name": "N", "role": "doctor", "password": "secret1"},
    )
    assert r.status_code == 403


def test_admin_can_create_and_list(client, db):
    tok = _token(db, Role.admin)
    r = client.post(
        "/accounts",
        headers=_auth(tok),
        json={"email": "new@x.io", "name": "New Doc", "role": "doctor", "password": "secret1"},
    )
    assert r.status_code == 201
    assert r.json()["email"] == "new@x.io"

    lst = client.get("/accounts", headers=_auth(tok))
    assert lst.status_code == 200
    emails = {u["email"] for u in lst.json()}
    assert {"admin@x.io", "new@x.io"} <= emails


def test_admin_create_duplicate_email_409(client, db):
    tok = _token(db, Role.admin)
    payload = {"email": "dup@x.io", "name": "D", "role": "doctor", "password": "secret1"}
    assert client.post("/accounts", headers=_auth(tok), json=payload).status_code == 201
    assert client.post("/accounts", headers=_auth(tok), json=payload).status_code == 409


def test_admin_patch_and_deactivate(client, db):
    tok = _token(db, Role.admin)
    created = client.post(
        "/accounts",
        headers=_auth(tok),
        json={"email": "e@x.io", "name": "E", "role": "doctor", "password": "secret1"},
    ).json()
    uid = created["id"]

    patched = client.patch(f"/accounts/{uid}", headers=_auth(tok), json={"name": "Renamed"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"

    deac = client.delete(f"/accounts/{uid}", headers=_auth(tok))
    assert deac.status_code == 200
    assert deac.json()["is_active"] is False

    assert client.patch("/accounts/9999", headers=_auth(tok), json={"name": "x"}).status_code == 404


def test_created_doctor_can_login(client, db):
    tok = _token(db, Role.admin)
    client.post(
        "/accounts",
        headers=_auth(tok),
        json={"email": "fresh@x.io", "name": "Fresh", "role": "doctor", "password": "welcome1"},
    )
    r = client.post("/auth/login", json={"email": "fresh@x.io", "password": "welcome1"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "doctor"
