import httpx

from pumpkit.main import app


async def test_contact_redirects_to_support_mailto():
    # httpx's client rejects a mailto: Location even with redirects off.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    request = httpx.Request("GET", "http://test/api/v1/support/contact")
    response = await transport.handle_async_request(request)
    assert response.status_code == 303
    assert response.headers["location"] == "mailto:support@example.com"


async def test_contact_redirects_with_support_email_alone(no_operator_details):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    request = httpx.Request("GET", "http://test/api/v1/support/contact")
    response = await transport.handle_async_request(request)
    assert response.status_code == 303
    assert response.headers["location"] == "mailto:support@example.com"


async def test_contact_answers_404_without_support_email(
    client, no_operator_details, no_support_email
):
    response = await client.get("/api/v1/support/contact")

    assert response.status_code == 404
