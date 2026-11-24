import time

import jwt
import pytest

from nexus_core.domain.exceptions import UnauthorizedException
from nexus_security.jwt import decode_access_token
from nexus_testkit import TEST_JWT_SECRET, sign_token


def test_valid_token_yields_payload_with_default_role():
    token = jwt.encode({"sub": "u1", "exp": int(time.time()) + 60}, TEST_JWT_SECRET, algorithm="HS256")
    payload = decode_access_token(token, TEST_JWT_SECRET)
    assert payload.sub == "u1"
    assert payload.role == "customer"
    assert payload.email is None


def test_expired_token_is_rejected_as_expired():
    with pytest.raises(UnauthorizedException, match="expirado"):
        decode_access_token(sign_token(exp_delta_s=-10), TEST_JWT_SECRET)


def test_token_signed_with_other_secret_is_rejected():
    forged = sign_token(secret="another-secret-of-sufficient-length-0123")
    with pytest.raises(UnauthorizedException, match="inválido"):
        decode_access_token(forged, TEST_JWT_SECRET)


def test_unsigned_alg_none_token_is_rejected():
    unsigned = jwt.encode({"sub": "admin", "role": "admin", "exp": int(time.time()) + 60}, None, algorithm="none")
    with pytest.raises(UnauthorizedException):
        decode_access_token(unsigned, TEST_JWT_SECRET)


def test_garbage_token_is_rejected():
    with pytest.raises(UnauthorizedException):
        decode_access_token("not.a.jwt", TEST_JWT_SECRET)


def test_email_verified_defaults_to_false_when_absent():
    from nexus_security.jwt import TokenPayload

    assert TokenPayload(sub="u", exp=1).email_verified is False
