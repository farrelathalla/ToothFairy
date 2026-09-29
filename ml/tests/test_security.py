import time

import jwt
import pytest

from app.models.user import Role, User
from app.security import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


def _user(id=1, role=Role.doctor):
    return User(id=id, email="d@x.io", name="D", role=role.value, password_hash="x", is_active=True)


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("doctor123")
    assert h != "doctor123"
    assert verify_password("doctor123", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_salted_unique():
    assert hash_password("same") != hash_password("same")


def test_verify_handles_garbage_hash():
    assert verify_password("x", "not-a-bcrypt-hash") is False


def test_token_round_trip_carries_sub_and_role():
    tok = create_token(_user(id=7, role=Role.admin))
    payload = decode_token(tok)
    assert payload["sub"] == "7"
    assert payload["role"] == "admin"


def test_expired_token_rejected():
    tok = create_token(_user(), expires_min=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(tok)


def test_tampered_token_rejected():
    tok = create_token(_user())
    with pytest.raises(jwt.PyJWTError):
        decode_token(tok + "tamper")
