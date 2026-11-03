"""
Serving a Media's preview and its file to the web app, through `GET /media/{id}/preview` and
`GET /media/{id}/file`: only to the User who attached it.
"""

from io import BytesIO

from PIL import Image

from tests.media_files import jpeg, png

API = "/api/v1"


async def _attach(client, post_id: str, data: bytes, name: str = "photo.png") -> dict:
    response = await client.post(
        f"{API}/posts/{post_id}/text/parts/1/media",
        files={"file": (name, data, "application/octet-stream")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_the_preview_is_a_small_image_of_the_file(client, subscribed, post_with):
    post_id = await post_with("A big picture.")
    media = await _attach(client, post_id, png(3000, 1500))

    response = await client.get(f"{API}{media['preview_url']}")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(response.content)) as preview:
        assert preview.size == (1200, 600)


async def test_the_file_comes_back_as_attached_with_the_type_its_bytes_name(
    client, subscribed, post_with
):
    post_id = await post_with("A photo.")
    original = jpeg()
    media = await _attach(client, post_id, original, name="photo.png")

    response = await client.get(f"{API}/media/{media['id']}/file")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == original


async def test_another_user_gets_neither(
    client, subscribed, post_with, sign_in_as_another_subscribed_user
):
    post_id = await post_with("Private.")
    media = await _attach(client, post_id, png())
    await sign_in_as_another_subscribed_user()

    preview = await client.get(f"{API}/media/{media['id']}/preview")
    file = await client.get(f"{API}/media/{media['id']}/file")

    assert preview.status_code == 404, preview.text
    assert file.status_code == 404, file.text


async def test_unknown_media_is_not_found(client, subscribed):
    response = await client.get(f"{API}/media/media_unknown/preview")

    assert response.status_code == 404, response.text
