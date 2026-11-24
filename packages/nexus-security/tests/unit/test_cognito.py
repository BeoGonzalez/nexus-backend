"""Verificacion de JWT de Amazon Cognito (RS256 + JWKS)."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from nexus_core.domain.exceptions import UnauthorizedException
from nexus_security.cognito import CognitoJwtVerifier

REGION = "us-east-1"
POOL = "us-east-1_TestPool"
CLIENT = "test-client-id"
ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _SigningKey:
    def __init__(self, key):
        self.key = key


class FakeJwksClient:
    """Sustituto de jwt.PyJWKClient: siempre devuelve la clave publica del pool de prueba."""

    def get_signing_key_from_jwt(self, token):
        return _SigningKey(_KEY.public_key())


def _token(key=_KEY, alg="RS256", **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "user-sub-1",
        "iss": ISSUER,
        "aud": CLIENT,
        "token_use": "id",
        "email": "ana@nexus.cl",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "k1"})


def _access(**overrides) -> str:
    base = {"token_use": "access", "aud": None, "client_id": CLIENT, "email": None, "username": "ana"}
    base.update(overrides)
    return _token(**base)


@pytest.fixture
def verifier():
    return CognitoJwtVerifier(REGION, POOL, CLIENT, jwks_client=FakeJwksClient())


def test_id_token_yields_sub_email_and_customer_role(verifier):
    payload = verifier.verify(_token())
    assert payload.sub == "user-sub-1"
    assert payload.email == "ana@nexus.cl"
    assert payload.role == "customer"


def test_admins_group_maps_to_admin_role(verifier):
    assert verifier.verify(_token(**{"cognito:groups": ["admins"]})).role == "admin"


def test_other_groups_stay_customer(verifier):
    assert verifier.verify(_token(**{"cognito:groups": ["beta"]})).role == "customer"


def test_access_token_with_matching_client_id_is_accepted(verifier):
    payload = verifier.verify(_access())
    assert payload.sub == "user-sub-1"
    assert payload.email is None


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _token(iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Other"), id="issuer"),
        pytest.param(lambda: _token(aud="another-client"), id="audience"),
        pytest.param(lambda: _access(client_id="another-client"), id="access-client-id"),
        pytest.param(lambda: _token(exp=int(time.time()) - 10), id="expired"),
        pytest.param(lambda: _token(key=_OTHER_KEY), id="foreign-signature"),
        pytest.param(lambda: _token(token_use="refresh"), id="token-use"),
        pytest.param(lambda: _token(token_use=None), id="no-token-use"),
        pytest.param(lambda: jwt.encode({"sub": "x", "iss": ISSUER, "aud": CLIENT, "token_use": "id",
                                         "exp": int(time.time()) + 60}, "a" * 40, algorithm="HS256"),
                     id="hs256-alg-confusion"),
        pytest.param(lambda: "not-a-jwt", id="garbage"),
    ],
)
def test_invalid_tokens_are_rejected(verifier, token):
    with pytest.raises(UnauthorizedException):
        verifier.verify(token())


def test_jwks_url_points_to_the_user_pool():
    v = CognitoJwtVerifier(REGION, POOL, CLIENT)
    assert v.jwks_url == f"{ISSUER}/.well-known/jwks.json"


@pytest.mark.parametrize("claim, expected", [(True, True), ("true", True), (False, False), ("false", False), (None, False)])
def test_email_verified_claim_is_carried(verifier, claim, expected):
    assert verifier.verify(_token(email_verified=claim)).email_verified is expected
