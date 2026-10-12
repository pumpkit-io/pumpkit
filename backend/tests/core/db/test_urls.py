import pytest

from pumpkit.core.db.urls import build_database_url

_PARTS = dict(user="u", password="p@ss/word", host="h", port="5432", database="d")


def test_no_ssl_when_disabled():
    assert build_database_url(driver="asyncpg", ssl="disable", **_PARTS) == (
        "postgresql+asyncpg://u:p%40ss%2Fword@h:5432/d"
    )


def test_required_ssl_asyncpg_uses_ssl_param():
    assert build_database_url(driver="asyncpg", ssl="require", **_PARTS).endswith("/d?ssl=require")


def test_required_ssl_psycopg2_uses_sslmode_param():
    url = build_database_url(driver="psycopg2", ssl="require", **_PARTS)
    assert url.startswith("postgresql+psycopg2://")
    assert url.endswith("/d?sslmode=require")


def test_default_driver_prefix():
    url = build_database_url(driver="default", ssl="require", **_PARTS)
    assert url.startswith("postgresql+psycopg2://")
    assert url.endswith("?sslmode=require")


def test_unknown_ssl_value_is_rejected():
    with pytest.raises(ValueError, match="POSTGRES_SSL"):
        build_database_url(driver="psycopg2", ssl="prefer", **_PARTS)
