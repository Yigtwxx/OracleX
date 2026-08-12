"""Tests for the API-key encryption helper."""

import pytest
from cryptography.fernet import Fernet

from services import secret_box
from services.secret_box import SecretBoxUnconfigured


@pytest.fixture
def configured(monkeypatch):
    """Point the helper at a throwaway encryption secret."""
    monkeypatch.setattr(
        secret_box.settings, "LLM_KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode()
    )


@pytest.fixture
def unconfigured(monkeypatch):
    monkeypatch.setattr(secret_box.settings, "LLM_KEY_ENCRYPTION_SECRET", "")


def test_roundtrip_returns_original(configured):
    ciphertext = secret_box.encrypt("gsk_supersecret_value")
    assert ciphertext != "gsk_supersecret_value"
    assert secret_box.decrypt(ciphertext) == "gsk_supersecret_value"


def test_ciphertext_differs_between_calls(configured):
    """Fernet embeds a timestamp+IV, so the same input must not produce a stable
    ciphertext an attacker could match against."""
    assert secret_box.encrypt("same") != secret_box.encrypt("same")


def test_is_configured_reflects_secret(configured):
    assert secret_box.is_configured() is True


def test_is_configured_false_without_secret(unconfigured):
    assert secret_box.is_configured() is False


def test_encrypt_refuses_without_secret(unconfigured):
    with pytest.raises(SecretBoxUnconfigured):
        secret_box.encrypt("gsk_value")


def test_malformed_secret_is_unconfigured(monkeypatch):
    monkeypatch.setattr(secret_box.settings, "LLM_KEY_ENCRYPTION_SECRET", "not-a-valid-key")
    assert secret_box.is_configured() is False
    with pytest.raises(SecretBoxUnconfigured):
        secret_box.encrypt("gsk_value")


def test_key_hint_is_last_four_characters(configured):
    assert secret_box.key_hint("gsk_abcdefghML8x") == "ML8x"


def test_key_hint_masks_short_keys(configured):
    """A key short enough that 4 characters would reveal most of it."""
    assert secret_box.key_hint("abc") == "****"
