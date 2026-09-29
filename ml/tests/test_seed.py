from app.security import verify_password
from app.services import accounts
from seed import DEFAULT_ACCOUNTS, seed_accounts


def test_seed_creates_default_accounts(db):
    created = seed_accounts(db)
    assert set(created) == {a["email"] for a in DEFAULT_ACCOUNTS}

    users = {u.email: u for u in accounts.list_users(db)}
    assert len(users) == 2
    admin = users["admin@toothfairy.com"]
    doctor = users["doctor@toothfairy.com"]
    assert admin.role == "admin"
    assert doctor.role == "doctor"
    assert verify_password("admin123", admin.password_hash)
    assert verify_password("doctor123", doctor.password_hash)


def test_seed_is_idempotent(db):
    seed_accounts(db)
    created_again = seed_accounts(db)
    assert created_again == []
    assert len(accounts.list_users(db)) == 2


def test_seeded_accounts_can_login(client, db):
    seed_accounts(db)
    r = client.post("/auth/login", json={"email": "admin@toothfairy.com", "password": "admin123"})
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"
