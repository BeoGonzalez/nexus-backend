"""Fixtures compartidas por todas las suites (paquetes y microservicios).

- Fija un JWT_SECRET de prueba antes de que cualquier servicio se importe.
- Levanta Postgres 16 y Redis 7 reales con Testcontainers (scope de sesión, bajo demanda) y
  SNS/SQS en memoria con moto (fixture aws_events).
- Marca como `integration` todo test que viva bajo un directorio `integration/`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from nexus_testkit import TEST_JWT_SECRET, sign_token

os.environ["JWT_SECRET"] = TEST_JWT_SECRET
os.environ["JWT_ALGORITHM"] = "HS256"

# Los servicios cargan `.env` (con credenciales reales). Las variables de entorno tienen
# prioridad sobre `.env` en pydantic-settings, así que neutralizamos todo lo que podría
# alcanzar infraestructura o proveedores reales. Los tests de integración pasan sus
# propias URLs (contenedores) explícitamente.
_INERT_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@127.0.0.1:1/test",
    "DATABASE_READ_URL": "postgresql+asyncpg://test:test@127.0.0.1:1/test",
    "REDIS_URL": "redis://127.0.0.1:1/0",
    "EVENTS_TOPIC_ARN": "",
    "EVENTS_QUEUE_URL": "",
    "CATALOG_SERVICE_URL": "http://catalog.test",
    "COGNITO_USER_POOL_ID": "",
    "COGNITO_APP_CLIENT_ID": "",
    "COGNITO_APP_CLIENT_SECRET": "",
    # Sin Cognito, auth-service solo emite tokens con el modo local activado explícitamente.
    "AUTH_LOCAL_MODE": "true",
    "LOCAL_ADMIN_EMAILS": "",
    # No vacías: el código sustituye valores vacíos por credenciales reales embebidas.
    "GROQ_API_KEY": "gsk_inert_test_key_not_valid",
    "PINECONE_API_KEY": "",
    "TAVILY_API_KEY": "",
    "CHEAPSHARK_ENABLED": "false",
    "ENABLE_CREWAI_ORCHESTRATION": "false",
    "ENABLE_LAYA_DECISION_ENGINE": "false",
    "LANGSMITH_TRACING": "false",
    "LANGSMITH_API_KEY": "",
    "LANGCHAIN_TRACING_V2": "false",
    "LANGCHAIN_API_KEY": "",
    "SMTP_USER": "inert-test-user@invalid.test",
    "SMTP_PASSWORD": "inert-test-password",
    "SMTP_HOST": "127.0.0.1",
    "SMTP_PORT": "1",
    "GMAIL_USER": "inert-test-user@invalid.test",
    "GMAIL_APP_PASSWORD": "inert-test-password",
}
os.environ.update(_INERT_ENV)

POSTGRES_IMAGE = "postgres:16-alpine"
REDIS_IMAGE = "redis:7-alpine"


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "integration" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.integration)


def _require_docker() -> None:
    try:
        import docker

        docker.from_env().ping()
    except Exception as exc:  # pragma: no cover - depende del entorno
        pytest.skip(f"Docker no disponible para Testcontainers: {exc}")


@pytest.fixture(scope="session")
def postgres_url():
    _require_docker()
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def redis_url():
    _require_docker()
    from testcontainers.community.redis import RedisContainer

    with RedisContainer(REDIS_IMAGE) as rc:
        host = rc.get_container_host_ip()
        port = rc.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture
def aws_events(monkeypatch):
    """SNS + SQS en memoria (moto): mismo contrato que en AWS (topic -> suscripcion raw con filtro
    por event_type -> cola). VisibilityTimeout 0: un mensaje no borrado reaparece de inmediato."""
    import json
    from types import SimpleNamespace

    import boto3
    from moto import mock_aws

    for key, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(key, value)

    with mock_aws():
        sns = boto3.client("sns", region_name="us-east-1")
        sqs = boto3.client("sqs", region_name="us-east-1")
        topic_arn = sns.create_topic(Name="nexus-events")["TopicArn"]

        def queue(name: str, filter_policy: dict | None = None) -> str:
            url = sqs.create_queue(QueueName=name, Attributes={"VisibilityTimeout": "0"})["QueueUrl"]
            arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
            attributes = {"RawMessageDelivery": "true"}
            if filter_policy:
                attributes |= {"FilterPolicy": json.dumps(filter_policy), "FilterPolicyScope": "MessageAttributes"}
            sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=arn, Attributes=attributes)
            return url

        yield SimpleNamespace(topic_arn=topic_arn, sns=sns, sqs=sqs, queue=queue)


@pytest.fixture
def make_token():
    return sign_token
