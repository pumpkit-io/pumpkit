GENERIC_MESSAGE = "If an account exists for that email, we've sent you a sign-in link."


async def test_requesting_a_magic_link_emails_one_sign_in_link(client, auth_outbox):
    response = await client.post(
        "/api/v1/login/magic-link/request", json={"email": "bob@example.com"}
    )

    assert response.status_code == 200
    assert response.json() == {"message": GENERIC_MESSAGE}
    assert len(auth_outbox.messages) == 1
    message = auth_outbox.messages[0]
    assert message.to == "bob@example.com"
    assert message.link_url.startswith("http://localhost:8000/api/v1/login/magic-link?token=")


async def test_failed_send_returns_the_error_and_an_immediate_retry_sends_an_email(
    client, auth_outbox, assert_reported_500
):
    auth_outbox.fail = True
    failed = await client.post(
        "/api/v1/login/magic-link/request", json={"email": "bob@example.com"}
    )

    assert_reported_500(failed)

    auth_outbox.fail = False
    retried = await client.post(
        "/api/v1/login/magic-link/request", json={"email": "bob@example.com"}
    )

    assert retried.status_code == 200
    assert retried.json() == {"message": GENERIC_MESSAGE}
    assert [message.to for message in auth_outbox.messages] == ["bob@example.com"]


async def test_two_requests_within_the_cooldown_send_one_email(client, auth_outbox):
    first = await client.post("/api/v1/login/magic-link/request", json={"email": "bob@example.com"})
    second = await client.post(
        "/api/v1/login/magic-link/request", json={"email": "bob@example.com"}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json() == {"message": GENERIC_MESSAGE}
    assert len(auth_outbox.messages) == 1
