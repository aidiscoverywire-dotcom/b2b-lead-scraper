"""Fernet encryption for stored API keys.

The Fernet key is DERIVED from the stable SECRET_KEY env var
(SHA256 -> urlsafe base64) — it is NEVER generated randomly per boot,
so encrypted keys stay readable across restarts and redeploys
(blueprint 7.4).
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import SECRET_KEY


def _fernet() -> Fernet:
    raw = hashlib.sha256(SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_value(plaintext: str) -> str:
    if plaintext is None:
        raise ValueError("cannot encrypt None")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Could not decrypt stored key — SECRET_KEY probably changed. "
            "Restore the original SECRET_KEY or re-enter the API keys."
        ) from exc
