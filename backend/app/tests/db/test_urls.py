import pytest

from app.db.urls import build_database_url

_PARTS = dict(user="u", password="p@ss/word", host="h", port="5432", database="d")


@pytest.mark.parametrize("env", ["local", "dev", "stg"])
def test_no_ssl_outside_prod(env):
    assert build_database_url(driver="asyncpg", env=env, **_PARTS) == (
        "postgresql+asyncpg://u:p%40ss%2Fword@h:5432/d"
    )


def test_prod_asyncpg_uses_ssl_param():
    assert build_database_url(driver="asyncpg", env="prod", **_PARTS).endswith("/d?ssl=require")


def test_prod_psycopg2_uses_sslmode_param():
    url = build_database_url(driver="psycopg2", env="prod", **_PARTS)
    assert url.startswith("postgresql+psycopg2://")
    assert url.endswith("/d?sslmode=require")


def test_default_driver_prefix():
    url = build_database_url(driver="default", env="prod", **_PARTS)
    assert url.startswith("postgresql+psycopg2://")
    assert url.endswith("?sslmode=require")
