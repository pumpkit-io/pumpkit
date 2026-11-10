import pytest


@pytest.mark.parametrize("action", ["use", "decline"])
async def test_photo_selection_endpoints_are_unavailable(client, action, fake_photo_fetcher):
    response = await client.post(f"/api/v1/x-connection/photo/{action}")

    assert response.status_code == 404
    assert fake_photo_fetcher.fetched == []
