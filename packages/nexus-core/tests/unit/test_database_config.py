import string

from hypothesis import given, strategies as st

from nexus_core.infrastructure.database import DatabaseConnectionConfig, create_db_engine


def normalize(url: str) -> str:
    return DatabaseConnectionConfig(database_url=url).normalized_url


def test_postgres_scheme_is_converted_to_asyncpg():
    assert normalize("postgres://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"


def test_postgresql_scheme_is_converted_to_asyncpg():
    assert normalize("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_asyncpg_url_is_left_untouched():
    assert normalize("postgresql+asyncpg://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_surrounding_whitespace_is_trimmed():
    assert normalize("  postgres://u:p@h/db \n") == "postgresql+asyncpg://u:p@h/db"


def test_libpq_only_query_params_are_stripped_and_others_kept():
    url = "postgres://u:p@h/db?sslmode=require&channel_binding=require&application_name=nexus"
    assert normalize(url) == "postgresql+asyncpg://u:p@h/db?application_name=nexus"


def test_stripping_is_case_insensitive():
    assert normalize("postgres://u:p@h/db?SSLMODE=require") == "postgresql+asyncpg://u:p@h/db"


def test_ssl_flag_produces_asyncpg_connect_args():
    assert DatabaseConnectionConfig(database_url="postgres://h/db", ssl=True).connect_args == {"ssl": "require"}
    assert DatabaseConnectionConfig(database_url="postgres://h/db").connect_args == {}


def test_engine_gets_failover_safe_pool_settings():
    engine = create_db_engine(DatabaseConnectionConfig(database_url="postgres://u:p@localhost/db"))
    try:
        assert engine.pool._pre_ping is True
        assert engine.pool._recycle == 1800
        assert engine.url.drivername == "postgresql+asyncpg"
    finally:
        engine.sync_engine.dispose()


_ident = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=12)
_param = st.sampled_from(["sslmode", "channel_binding", "endpoint", "ssl", "application_name", "connect_timeout"])


@given(
    scheme=st.sampled_from(["postgres://", "postgresql://", "postgresql+asyncpg://"]),
    host=_ident,
    db=_ident,
    params=st.lists(st.tuples(_param, _ident), max_size=4),
)
def test_normalization_is_idempotent_and_never_keeps_libpq_params(scheme, host, db, params):
    query = "&".join(f"{k}={v}" for k, v in params)
    url = f"{scheme}u:p@{host}/{db}" + (f"?{query}" if query else "")
    once = normalize(url)
    assert normalize(once) == once
    assert once.startswith("postgresql+asyncpg://")
    for bad in ("sslmode=", "channel_binding=", "endpoint=", "ssl="):
        assert bad not in once.split("?", 1)[-1] if "?" in once else True
