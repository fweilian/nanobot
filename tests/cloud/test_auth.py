from __future__ import annotations

import pytest

from nanobot.cloud.auth import JwtTokenVerifier


def test_verify_hs256_token_extracts_user_id():
    jwt = pytest.importorskip("jwt")
    secret = "this-is-a-long-test-secret-for-hs256"
    token = jwt.encode({"sub": "alice", "iss": "issuer"}, secret, algorithm="HS256")
    verifier = JwtTokenVerifier(
        algorithms=["HS256"],
        issuer="issuer",
        shared_secret=secret,
    )

    user = verifier.verify(token)

    assert user.user_id == "alice"


def test_verify_rejects_invalid_token():
    secret = "this-is-a-long-test-secret-for-hs256"
    verifier = JwtTokenVerifier(
        algorithms=["HS256"],
        issuer="issuer",
        shared_secret=secret,
    )

    with pytest.raises(Exception):
        verifier.verify("bad-token")
