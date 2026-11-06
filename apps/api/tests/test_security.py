import time

import pytest

from app import security


def test_password_hash_verifies_and_is_salted():
    h1 = security.hash_password("correct horse battery")
    h2 = security.hash_password("correct horse battery")
    assert h1 != h2
    assert security.verify_password(h1, "correct horse battery")
    assert not security.verify_password(h1, "wrong password!!")


def test_verify_password_rejects_garbage_hash():
    assert not security.verify_password("not-a-hash", "whatever")


def test_access_token_round_trip():
    token, _ = security.create_token(7, "access", ttl_seconds=60)
    claims = security.decode_token(token, "access")
    assert claims["sub"] == "7" and claims["typ"] == "access"


def test_token_kinds_are_not_interchangeable():
    refresh, _ = security.create_token(7, "refresh", ttl_seconds=60)
    with pytest.raises(security.TokenError):
        security.decode_token(refresh, "access")


def test_expired_token_is_rejected():
    token, _ = security.create_token(7, "access", ttl_seconds=-1)
    with pytest.raises(security.TokenError):
        security.decode_token(token, "access")


def test_tampered_token_is_rejected():
    token, _ = security.create_token(7, "access", ttl_seconds=60)
    with pytest.raises(security.TokenError):
        security.decode_token(token[:-2] + ("AA" if token[-2:] != "AA" else "BB"), "access")


def test_token_signed_with_another_key_is_rejected():
    import jwt

    forged = jwt.encode(
        {"sub": "1", "typ": "access", "exp": int(time.time()) + 60, "jti": "x"},
        "some-other-secret-some-other-secret",
        algorithm="HS256",
    )
    with pytest.raises(security.TokenError):
        security.decode_token(forged, "access")


def test_none_algorithm_is_rejected():
    import jwt

    unsigned = jwt.encode({"sub": "1", "typ": "access", "jti": "x"}, None, algorithm="none")
    with pytest.raises(security.TokenError):
        security.decode_token(unsigned, "access")


def test_each_token_has_a_unique_jti():
    _, a = security.create_token(1, "refresh", ttl_seconds=60)
    _, b = security.create_token(1, "refresh", ttl_seconds=60)
    assert a != b
