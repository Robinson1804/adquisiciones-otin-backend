"""Unit tests for app.core.security — hash, verify, token lifecycle."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from app.config import settings
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def test_hash_roundtrip():
    plain = "MyS3cur3P@ss!"
    hashed = hash_password(plain)
    assert hashed.startswith("$2b$"), "Expected bcrypt hash"
    assert verify_password(plain, hashed) is True


def test_tampered_hash():
    plain = "MyS3cur3P@ss!"
    hashed = hash_password(plain)
    # Flip the last character to simulate tampering
    tampered = hashed[:-1] + ("X" if hashed[-1] != "X" else "Y")
    assert verify_password(plain, tampered) is False


def test_different_password_does_not_verify():
    hashed = hash_password("correct_password")
    assert verify_password("wrong_password", hashed) is False


# ---------------------------------------------------------------------------
# JWT create / decode
# ---------------------------------------------------------------------------
def test_create_and_decode_token():
    token = create_access_token(sub="42", username="alice", rol="EDITOR")
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["username"] == "alice"
    assert payload["rol"] == "EDITOR"
    assert "exp" in payload


def test_decode_expired_token():
    expired_payload = {
        "sub": "1",
        "username": "admin",
        "rol": "ADMIN",
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    expired_token = jwt.encode(
        expired_payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    with pytest.raises(HTTPException) as exc_info:
        decode_token(expired_token)
    assert exc_info.value.status_code == 401


def test_decode_bad_signature():
    token = create_access_token(sub="1", username="admin", rol="ADMIN")
    # Tamper the last character
    tampered = token[:-1] + ("X" if token[-1] != "X" else "Y")
    with pytest.raises(HTTPException) as exc_info:
        decode_token(tampered)
    assert exc_info.value.status_code == 401


def test_decode_garbage_token():
    with pytest.raises(HTTPException) as exc_info:
        decode_token("not.a.token")
    assert exc_info.value.status_code == 401
