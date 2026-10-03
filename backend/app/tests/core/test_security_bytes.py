from app.core.security import decrypt_bytes, encrypt_bytes


def test_roundtrip():
    blob = b"\x00\x01binary\xff"
    token = encrypt_bytes(blob)
    assert token != blob
    assert decrypt_bytes(token) == blob


def test_empty_passthrough():
    assert encrypt_bytes(b"") == b""
    assert decrypt_bytes(b"") == b""


def test_invalid_token_returns_empty_bytes():
    assert decrypt_bytes(b"not-a-fernet-token") == b""
