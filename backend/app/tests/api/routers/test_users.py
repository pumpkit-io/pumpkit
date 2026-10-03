_TINY_JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


async def test_get_me_includes_avatar(client):
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200
    assert response.json() == {
        "email": "alice@example.com",
        "first_name": None,
        "last_name": None,
        "avatar_data_url": None,
    }


async def test_patch_updates_only_present_fields_and_derives_display_name(client, db, user):
    response = await client.patch(
        "/api/v1/users/me", json={"first_name": "  Ada ", "last_name": "Lovelace"}
    )
    assert response.status_code == 200
    assert response.json()["first_name"] == "Ada"
    await db.refresh(user)
    assert user.display_name == "Ada Lovelace"

    response = await client.patch("/api/v1/users/me", json={"avatar_data_url": _TINY_JPEG})
    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Ada"  # untouched because omitted
    assert body["avatar_data_url"] == _TINY_JPEG


async def test_patch_null_clears_avatar(client):
    await client.patch("/api/v1/users/me", json={"avatar_data_url": _TINY_JPEG})
    response = await client.patch("/api/v1/users/me", json={"avatar_data_url": None})
    assert response.json()["avatar_data_url"] is None


async def test_clearing_names_falls_back_to_email_local_part(client, db, user):
    await client.patch("/api/v1/users/me", json={"first_name": "Ada"})
    await client.patch("/api/v1/users/me", json={"first_name": "   ", "last_name": None})
    await db.refresh(user)
    assert user.first_name is None
    assert user.display_name == "alice"


async def test_rejects_long_name(client):
    response = await client.patch("/api/v1/users/me", json={"first_name": "x" * 81})
    assert response.status_code == 422


async def test_rejects_non_image_data_url(client):
    response = await client.patch(
        "/api/v1/users/me", json={"avatar_data_url": "data:text/html;base64,PGgxPg=="}
    )
    assert response.status_code == 422


async def test_rejects_oversized_avatar(client):
    huge = "data:image/png;base64," + "A" * 220_001
    response = await client.patch("/api/v1/users/me", json={"avatar_data_url": huge})
    assert response.status_code == 422


async def test_rejects_avatar_with_trailing_newline(client):
    response = await client.patch("/api/v1/users/me", json={"avatar_data_url": _TINY_JPEG + "\n"})
    assert response.status_code == 422
