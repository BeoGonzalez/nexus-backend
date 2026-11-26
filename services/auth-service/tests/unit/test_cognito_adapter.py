import base64
import hashlib
import hmac

import boto3
import jwt
import pytest
from botocore.stub import ANY, Stubber

from auth_service.config import Settings
from auth_service.infrastructure.cognito import CognitoAdapter, calculate_secret_hash
from nexus_core.domain.exceptions import BusinessRuleViolationException, UnauthorizedException
from nexus_testkit import TEST_JWT_SECRET


@pytest.fixture
def cognito(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    adapter = CognitoAdapter()
    adapter.settings = Settings(
        COGNITO_USER_POOL_ID="us-east-1_TestPool",
        COGNITO_APP_CLIENT_ID="client-id",
        COGNITO_APP_CLIENT_SECRET="client-secret",
    )
    client = boto3.client("cognito-idp", region_name="us-east-1")
    stub = Stubber(client)
    monkeypatch.setattr(adapter, "_get_client", lambda: client)
    with stub:
        yield adapter, stub
        stub.assert_no_pending_responses()


def test_secret_hash_matches_aws_reference_algorithm():
    expected = base64.b64encode(
        hmac.new(b"client-secret", b"a@b.clclient-id", hashlib.sha256).digest()
    ).decode()
    assert calculate_secret_hash("a@b.cl", "client-id", "client-secret") == expected


async def test_authenticate_sends_password_auth_with_secret_hash(cognito):
    adapter, stub = cognito
    stub.add_response(
        "initiate_auth",
        {"AuthenticationResult": {"AccessToken": "A", "IdToken": "I", "RefreshToken": "R",
                                  "ExpiresIn": 300, "TokenType": "Bearer"}},
        {"AuthFlow": "USER_PASSWORD_AUTH", "ClientId": "client-id",
         "AuthParameters": {"USERNAME": "a@b.cl", "PASSWORD": "pw123456",
                            "SECRET_HASH": calculate_secret_hash("a@b.cl", "client-id", "client-secret")}},
    )
    tokens = await adapter.authenticate("a@b.cl", "pw123456")
    assert tokens == {"access_token": "A", "id_token": "I", "refresh_token": "R",
                      "token_type": "Bearer", "expires_in": 300}


@pytest.mark.parametrize("code", ["NotAuthorizedException", "UserNotFoundException", "UserNotConfirmedException"])
async def test_cognito_auth_errors_become_unauthorized(cognito, code):
    adapter, stub = cognito
    stub.add_client_error("initiate_auth", service_error_code=code)
    with pytest.raises(UnauthorizedException):
        await adapter.authenticate("a@b.cl", "pw123456")


async def test_register_returns_subject_and_confirmation_state(cognito):
    adapter, stub = cognito
    stub.add_response(
        "sign_up",
        {"UserSub": "sub-9", "UserConfirmed": False},
        {"ClientId": "client-id", "Username": "a@b.cl", "Password": "pw123456",
         "UserAttributes": ANY, "SecretHash": ANY},
    )
    assert await adapter.register("a@b.cl", "pw123456", "Ana") == {"user_sub": "sub-9", "user_confirmed": False}


async def test_register_duplicate_email_is_business_rule_violation(cognito):
    adapter, stub = cognito
    stub.add_client_error("sign_up", service_error_code="UsernameExistsException")
    with pytest.raises(BusinessRuleViolationException, match="Ya existe"):
        await adapter.register("a@b.cl", "pw123456", "Ana")


async def test_refresh_with_revoked_token_is_unauthorized(cognito):
    adapter, stub = cognito
    stub.add_client_error("initiate_auth", service_error_code="NotAuthorizedException")
    with pytest.raises(UnauthorizedException):
        await adapter.refresh_tokens("revoked", "a@b.cl")


# ── Modo local (Cognito no configurado): es lo que correría en EKS si faltan las variables ──

@pytest.fixture
def local_adapter():
    adapter = CognitoAdapter()
    assert adapter.is_configured is False
    return adapter


async def test_local_mode_issues_token_verifiable_with_service_secret(local_adapter):
    await local_adapter.register("ana@b.cl", "pw123456", "Ana")
    tokens = await local_adapter.authenticate("ana@b.cl", "pw123456")
    claims = jwt.decode(tokens["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["email"] == "ana@b.cl"
    assert claims["role"] == "customer"



async def test_local_mode_rejects_wrong_password_for_registered_user(local_adapter):
    await local_adapter.register("ana@b.cl", "correct-pass", "Ana")
    with pytest.raises(UnauthorizedException):
        await local_adapter.authenticate("ana@b.cl", "wrong-pass")



async def test_local_mode_does_not_grant_admin_from_email_text(local_adapter):
    await local_adapter.register("notadmin.admin@evil.cl", "correct-pass", "Eve")
    tokens = await local_adapter.authenticate("notadmin.admin@evil.cl", "correct-pass")
    claims = jwt.decode(tokens["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["role"] != "admin"



async def test_local_mode_refresh_rejects_unknown_refresh_token(local_adapter):
    with pytest.raises(UnauthorizedException):
        await local_adapter.refresh_tokens("made-up-token", "victim@b.cl")


@pytest.mark.parametrize(
    ("pool_id", "client_id"),
    [
        # Valores tal cual vienen en .env.example: copiar el ejemplo no debe activar Cognito.
        ("us-east-1_xxxxxxxxx", "xxxxxxxxxxxxxxxxxxxxxxxxxx"),
        ("your-user-pool-id", "client-id"),
        ("us-east-1_TestPool", "your-app-client-id"),
    ],
)
def test_placeholder_cognito_values_are_not_configured(pool_id, client_id):
    adapter = CognitoAdapter()
    adapter.settings = Settings(COGNITO_USER_POOL_ID=pool_id, COGNITO_APP_CLIENT_ID=client_id)
    assert adapter.is_configured is False


async def test_placeholder_cognito_values_register_locally_without_calling_aws(monkeypatch):
    adapter = CognitoAdapter()
    adapter.settings = Settings(
        COGNITO_USER_POOL_ID="us-east-1_xxxxxxxxx",
        COGNITO_APP_CLIENT_ID="xxxxxxxxxxxxxxxxxxxxxxxxxx",
        AUTH_LOCAL_MODE=True,
        JWT_SECRET=TEST_JWT_SECRET,
    )
    monkeypatch.setattr(adapter, "_get_client", lambda: pytest.fail("no debe llamar a Cognito"))
    assert (await adapter.register("ana@b.cl", "pw123456", "Ana"))["user_confirmed"] is True


# ── Modo local fail-closed y tokens reales ──

@pytest.fixture
def unconfigured_adapter():
    adapter = CognitoAdapter()
    adapter.settings = Settings(AUTH_LOCAL_MODE=False)
    assert adapter.is_configured is False
    return adapter


async def test_without_cognito_or_local_flag_login_fails_closed(unconfigured_adapter):
    with pytest.raises(UnauthorizedException):
        await unconfigured_adapter.authenticate("ana@b.cl", "pw123456")


async def test_without_cognito_or_local_flag_register_fails_closed(unconfigured_adapter):
    with pytest.raises(UnauthorizedException):
        await unconfigured_adapter.register("ana@b.cl", "pw123456", "Ana")


async def test_without_cognito_or_local_flag_refresh_fails_closed(unconfigured_adapter):
    with pytest.raises(UnauthorizedException):
        await unconfigured_adapter.refresh_tokens("any-token", "ana@b.cl")


async def test_local_mode_rejects_unregistered_user(local_adapter):
    with pytest.raises(UnauthorizedException):
        await local_adapter.authenticate("ghost@b.cl", "pw123456")


async def test_local_mode_grants_admin_only_to_listed_emails(local_adapter):
    local_adapter.settings = Settings(AUTH_LOCAL_MODE=True, LOCAL_ADMIN_EMAILS="boss@nexus.cl, other@nexus.cl")
    await local_adapter.register("boss@nexus.cl", "pw123456", "Boss")
    tokens = await local_adapter.authenticate("boss@nexus.cl", "pw123456")
    claims = jwt.decode(tokens["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["role"] == "admin"


async def test_local_mode_refresh_accepts_issued_token(local_adapter):
    await local_adapter.register("ana@b.cl", "pw123456", "Ana")
    tokens = await local_adapter.authenticate("ana@b.cl", "pw123456")
    refreshed = await local_adapter.refresh_tokens(tokens["refresh_token"], "ana@b.cl")
    claims = jwt.decode(refreshed["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["email"] == "ana@b.cl"


async def test_local_mode_refresh_ignores_client_supplied_email(local_adapter):
    await local_adapter.register("ana@b.cl", "pw123456", "Ana")
    tokens = await local_adapter.authenticate("ana@b.cl", "pw123456")
    refreshed = await local_adapter.refresh_tokens(tokens["refresh_token"], "victim@b.cl")
    claims = jwt.decode(refreshed["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["email"] == "ana@b.cl"


async def test_local_mode_refresh_token_is_single_use(local_adapter):
    await local_adapter.register("ana@b.cl", "pw123456", "Ana")
    tokens = await local_adapter.authenticate("ana@b.cl", "pw123456")
    refreshed = await local_adapter.refresh_tokens(tokens["refresh_token"])
    assert refreshed["refresh_token"] != tokens["refresh_token"]
    with pytest.raises(UnauthorizedException):
        await local_adapter.refresh_tokens(tokens["refresh_token"])


async def test_local_mode_email_is_case_and_space_insensitive(local_adapter):
    await local_adapter.register("Ana@B.cl ", "pw123456", "Ana")
    tokens = await local_adapter.authenticate("ana@b.cl", "pw123456")
    claims = jwt.decode(tokens["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["email"] == "ana@b.cl"


async def test_local_mode_duplicate_register_is_rejected(local_adapter):
    await local_adapter.register("ana@b.cl", "pw123456", "Ana")
    with pytest.raises(BusinessRuleViolationException, match="Ya existe"):
        await local_adapter.register("ana@b.cl", "other-pass", "Eve")
    await local_adapter.authenticate("ana@b.cl", "pw123456")


def test_password_hash_is_salted_and_verifiable():
    from auth_service.infrastructure.cognito import _hash_password, _verify_password

    first, second = _hash_password("pw123456"), _hash_password("pw123456")
    assert first != second
    assert "pw123456" not in first
    assert _verify_password("pw123456", first)
    assert not _verify_password("nope", first)


async def test_local_mode_token_marks_email_as_verified(local_adapter):
    await local_adapter.register("ana@b.cl", "pw123456", "Ana")
    tokens = await local_adapter.authenticate("ana@b.cl", "pw123456")
    claims = jwt.decode(tokens["id_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert claims["email_verified"] is True


async def test_local_mode_without_explicit_jwt_secret_refuses_to_issue_tokens(monkeypatch):
    """A07/A02: nada de firmar tokens con un secreto por defecto conocido."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    adapter = CognitoAdapter()
    adapter.settings = Settings(_env_file=None, AUTH_LOCAL_MODE=True, COGNITO_USER_POOL_ID="", COGNITO_APP_CLIENT_ID="")
    with pytest.raises(UnauthorizedException):
        await adapter.register("ana@b.cl", "12345678", "Ana")
    with pytest.raises(UnauthorizedException):
        await adapter.authenticate("ana@b.cl", "12345678")


async def _auth_error_message(cognito, code: str, message: str = "") -> str:
    adapter, stub = cognito
    stub.add_client_error("initiate_auth", service_error_code=code, service_message=message)
    with pytest.raises(UnauthorizedException) as exc:
        await adapter.authenticate("a@b.cl", "pw123456")
    return exc.value.message


async def test_unknown_user_and_wrong_password_are_indistinguishable(cognito):
    """A07: sin enumeración de usuarios por el mensaje de login."""
    not_found = await _auth_error_message(cognito, "UserNotFoundException")
    wrong_pw = await _auth_error_message(cognito, "NotAuthorizedException")
    assert not_found == wrong_pw


@pytest.mark.parametrize("op", ["authenticate", "register", "forgot_password", "resend_confirmation_code"])
async def test_unexpected_cognito_errors_do_not_leak_internal_details(cognito, op):
    """A10: el texto crudo de AWS (request ids, ARNs, políticas internas) nunca llega al cliente."""
    adapter, stub = cognito
    internal = "arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_SECRET RequestId abc-123"
    api = {"authenticate": "initiate_auth", "register": "sign_up", "forgot_password": "forgot_password",
           "resend_confirmation_code": "resend_confirmation_code"}[op]
    stub.add_client_error(api, service_error_code="InternalErrorException", service_message=internal)
    args = {"authenticate": ("a@b.cl", "pw123456"), "register": ("a@b.cl", "Pw123456!", "Ana"),
            "forgot_password": ("a@b.cl",), "resend_confirmation_code": ("a@b.cl",)}[op]
    with pytest.raises(Exception) as exc:
        await getattr(adapter, op)(*args)
    text = str(getattr(exc.value, "message", exc.value))
    assert "arn:aws" not in text and "RequestId" not in text and "InternalErrorException" not in text


def test_adapter_does_not_offer_unverified_token_decoding():
    # A07/A08: decodificar un JWT sin verificar la firma aceptaría tokens falsificados.
    # La verificación real vive en nexus_security (RS256 contra el JWKS del pool).
    assert not hasattr(CognitoAdapter, "get_user_from_token")


@pytest.mark.parametrize(
    "op, call, args",
    [
        ("initiate_auth", "refresh_tokens", ("refresh-token-value", "a@b.cl")),
        ("forgot_password", "forgot_password", ("a@b.cl",)),
        ("confirm_forgot_password", "confirm_forgot_password", ("a@b.cl", "123456", "N3w-Passw0rd!")),
    ],
)
async def test_cognito_failures_log_only_the_error_code(cognito, caplog, op, call, args):
    # A09: el log registra el código de AWS, nunca el mensaje crudo (puede incluir datos del usuario o tokens).
    adapter, stub = cognito
    stub.add_client_error(op, service_error_code="InternalErrorException", service_message="detalle-sensible-xyz")
    with pytest.raises((UnauthorizedException, BusinessRuleViolationException)):
        await getattr(adapter, call)(*args)
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "InternalErrorException" in logged
    assert "detalle-sensible-xyz" not in logged
