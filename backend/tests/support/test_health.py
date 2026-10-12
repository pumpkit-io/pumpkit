from sqlalchemy.exc import OperationalError

from pumpkit.core.db.session import get_async_db
from pumpkit.main import app


class _UnreachableDatabase:
    async def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


async def test_health_is_ok_with_a_working_database(client):
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_is_not_rate_limited(client):
    # Above the 120/minute that /instance, the most generous public route, allows.
    statuses = {(await client.get("/api/v1/health")).status_code for _ in range(150)}

    assert statuses == {200}


async def test_health_is_unavailable_when_the_database_session_raises(client):
    app.dependency_overrides[get_async_db] = lambda: _UnreachableDatabase()

    response = await client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
