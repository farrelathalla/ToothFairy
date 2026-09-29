import pytest

from app.models.user import Role
from app.security import verify_password
from app.services import accounts
from app.services.errors import EmailExists, UserNotFound


def test_create_user_hashes_password_and_normalizes_email(db):
    u = accounts.create_user(db, email="  Doctor@X.IO ", name="Dr A", password="secret1", role=Role.doctor)
    assert u.id is not None
    assert u.email == "doctor@x.io"          # trimmed + lowercased
    assert u.role == "doctor"
    assert u.is_active is True
    assert u.password_hash != "secret1"
    assert verify_password("secret1", u.password_hash)


def test_duplicate_email_raises(db):
    accounts.create_user(db, email="a@x.io", name="A", password="secret1")
    with pytest.raises(EmailExists):
        accounts.create_user(db, email="A@x.io", name="A2", password="secret2")


def test_list_users_returns_all(db):
    accounts.create_user(db, email="a@x.io", name="A", password="secret1")
    accounts.create_user(db, email="b@x.io", name="B", password="secret1", role=Role.admin)
    users = accounts.list_users(db)
    assert {u.email for u in users} == {"a@x.io", "b@x.io"}


def test_get_by_email_and_get_user(db):
    u = accounts.create_user(db, email="a@x.io", name="A", password="secret1")
    assert accounts.get_by_email(db, "A@X.IO").id == u.id
    assert accounts.get_user(db, u.id).id == u.id


def test_get_user_missing_raises(db):
    with pytest.raises(UserNotFound):
        accounts.get_user(db, 999)


def test_update_user_changes_fields_and_password(db):
    u = accounts.create_user(db, email="a@x.io", name="A", password="secret1")
    accounts.update_user(db, u.id, name="Renamed", role=Role.admin, password="newpass1")
    refreshed = accounts.get_user(db, u.id)
    assert refreshed.name == "Renamed"
    assert refreshed.role == "admin"
    assert verify_password("newpass1", refreshed.password_hash)


def test_deactivate_user_soft_deletes(db):
    u = accounts.create_user(db, email="a@x.io", name="A", password="secret1")
    accounts.deactivate_user(db, u.id)
    assert accounts.get_user(db, u.id).is_active is False
