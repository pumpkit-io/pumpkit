import httpx

from app.main import app


async def test_contact_redirects_to_support_mailto():
    # httpx's client rejects a mailto: Location even with redirects off.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    request = httpx.Request("GET", "http://test/api/v1/support/contact")
    response = await transport.handle_async_request(request)
    assert response.status_code == 303
    assert response.headers["location"] == "mailto:support@example.com"
