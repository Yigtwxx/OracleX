"""
Symmetric encryption for per-user LLM API keys.

The backend talks to Supabase with the service-role key, so Row Level Security
offers no protection against a database dump. Keys are therefore encrypted at
rest with a secret that lives only in the environment.
"""

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from config import settings

logger = logging.getLogger(__name__)

_HINT_LENGTH = 4


class SecretBoxUnconfigured(RuntimeError):
    """LLM_KEY_ENCRYPTION_SECRET is missing or not a valid Fernet key."""


@lru_cache(maxsize=4)
def _fernet_for(secret: str) -> Fernet:
    """Cached per secret value, so tests can swap secrets without a reset hook."""
    return Fernet(secret.encode())


def _box() -> Fernet:
    secret = settings.LLM_KEY_ENCRYPTION_SECRET
    if not secret:
        raise SecretBoxUnconfigured(
            "LLM_KEY_ENCRYPTION_SECRET is not set — per-user API keys are disabled."
        )
    try:
        return _fernet_for(secret)
    except (ValueError, TypeError) as e:
        raise SecretBoxUnconfigured("LLM_KEY_ENCRYPTION_SECRET is not a valid Fernet key.") from e


def is_configured() -> bool:
    """True if keys can be encrypted and decrypted right now."""
    try:
        _box()
    except SecretBoxUnconfigured:
        return False
    return True


def encrypt(plaintext: str) -> str:
    """Encrypt an API key for storage. Raises SecretBoxUnconfigured if disabled."""
    return _box().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """
    Decrypt a stored API key.

    Raises SecretBoxUnconfigured when the stored value cannot be read with the
    current secret — which is what happens if the secret is rotated without
    re-encrypting existing rows.
    """
    try:
        return _box().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise SecretBoxUnconfigured(
            "Stored key could not be decrypted with the current "
            "LLM_KEY_ENCRYPTION_SECRET; the user must re-enter it."
        ) from e


def key_hint(plaintext: str) -> str:
    """
    The last few characters of a key, for display.

    Short keys are fully masked rather than mostly revealed.
    """
    if len(plaintext) <= _HINT_LENGTH * 2:
        return "*" * _HINT_LENGTH
    return plaintext[-_HINT_LENGTH:]
