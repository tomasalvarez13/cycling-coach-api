from app.core.security import (
    create_signed_state,
    decode_signed_state,
    decrypt_secret,
    encrypt_secret,
)


def test_encrypt_and_decrypt_secret_roundtrip() -> None:
    encrypted = encrypt_secret("super-secret-token")

    assert encrypted != "super-secret-token"
    assert decrypt_secret(encrypted) == "super-secret-token"


def test_signed_state_roundtrip() -> None:
    state = create_signed_state({"user_id": "user-123"}, expires_in_minutes=5)
    payload = decode_signed_state(state)

    assert payload["user_id"] == "user-123"
    assert payload["type"] == "oauth_state"
