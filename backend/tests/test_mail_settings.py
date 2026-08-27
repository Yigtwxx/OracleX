"""
Where the SMTP relay's settings come from, and what leaves this module.

The interesting behaviour is the resolution order — panel over environment,
field by field — and the two things that must never be true: the password
reaching a response, and an empty box in the panel silently blanking a working
value that came from `.env`.
"""

import json
import os
import stat

import pytest

from services import mail_settings_service, secret_box


@pytest.fixture
def store(monkeypatch, tmp_path):
    """The settings file, redirected away from the real backend/data."""
    path = tmp_path / "mail_settings.json"
    monkeypatch.setattr(mail_settings_service, "_STORE_PATH", str(path))
    return path


@pytest.fixture
def env_relay(monkeypatch):
    """An environment that already names a working relay."""
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_HOST", "env.example.com")
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_USER", "env@example.com")
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_PASSWORD", "env-password")
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_FROM", "")
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_FROM_NAME", "Oracle-X")
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_REPLY_TO", "")
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_SSL", False)
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_STARTTLS", True)


@pytest.fixture
def encryptable(monkeypatch):
    """A real Fernet key, so a password can actually be stored."""
    from cryptography.fernet import Fernet

    monkeypatch.setattr(
        secret_box.settings, "LLM_KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode()
    )


# ── Resolution ──────────────────────────────────────────────────────────────


def test_environment_is_used_when_nothing_was_set_in_the_panel(store, env_relay):
    current = mail_settings_service.resolved()

    assert current.host == "env.example.com"
    assert current.configured
    assert mail_settings_service.source() == "env"


def test_panel_overrides_the_environment(store, env_relay):
    mail_settings_service.save({"host": "panel.example.com"}, None)

    assert mail_settings_service.resolved().host == "panel.example.com"
    assert mail_settings_service.source() == "panel"


def test_a_field_the_panel_did_not_touch_still_comes_from_the_environment(store, env_relay):
    mail_settings_service.save({"host": "panel.example.com"}, None)

    # Only the host was set here; the account must not be lost with it.
    assert mail_settings_service.resolved().user == "env@example.com"


def test_an_empty_field_does_not_blank_a_working_value(store, env_relay):
    # An untouched box in the panel arrives as "", and treating that as an
    # override would take a working relay down on an unrelated save.
    mail_settings_service.save({"host": "", "from_name": "Desk"}, None)

    current = mail_settings_service.resolved()
    assert current.host == "env.example.com"
    assert current.from_name == "Desk"


def test_reply_to_can_be_cleared(store, env_relay, monkeypatch):
    monkeypatch.setattr(mail_settings_service.settings, "SMTP_REPLY_TO", "old@example.com")
    mail_settings_service.save({"reply_to": ""}, None)

    assert mail_settings_service.resolved().reply_to == ""


def test_sender_falls_back_to_the_authenticated_account(store, env_relay):
    # SPF and DKIM authenticate this domain, and Gmail's relay rewrites a From
    # that is not the account — so the fallback is the correct default, not a
    # convenience.
    assert mail_settings_service.resolved().sender == "env@example.com"


def test_an_explicit_from_address_wins(store, env_relay):
    mail_settings_service.save({"from_address": "desk@example.com"}, None)

    assert mail_settings_service.resolved().sender == "desk@example.com"


# ── The password ────────────────────────────────────────────────────────────


def test_a_stored_password_round_trips(store, env_relay, encryptable):
    mail_settings_service.save({"host": "panel.example.com"}, "app-password")

    assert mail_settings_service.resolved().password == "app-password"


def test_a_stored_password_is_not_written_in_the_clear(store, env_relay, encryptable):
    mail_settings_service.save({"host": "panel.example.com"}, "app-password")

    raw = store.read_text()
    assert "app-password" not in raw, "the file is copied into backups; it must not hold plaintext"


def test_the_settings_file_is_not_world_readable(store, env_relay, encryptable):
    mail_settings_service.save({"host": "panel.example.com"}, "app-password")

    mode = stat.S_IMODE(os.stat(store).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_the_public_view_never_carries_the_password(store, env_relay, encryptable):
    mail_settings_service.save({"host": "panel.example.com"}, "app-password")

    view = mail_settings_service.public_view()
    assert "password" not in view
    assert view["has_password"] is True
    assert "app-password" not in json.dumps(view)


def test_omitting_the_password_leaves_the_stored_one_alone(store, env_relay, encryptable):
    mail_settings_service.save({"host": "panel.example.com"}, "app-password")
    mail_settings_service.save({"from_name": "Desk"}, None)

    assert mail_settings_service.resolved().password == "app-password"


def test_an_empty_password_deletes_the_stored_one(store, env_relay, encryptable):
    mail_settings_service.save({"host": "panel.example.com"}, "app-password")
    mail_settings_service.save({}, "")

    # Falls back to the environment's, which is the documented resolution order.
    assert mail_settings_service.resolved().password == "env-password"


def test_storing_a_password_is_refused_without_an_encryption_secret(store, env_relay, monkeypatch):
    monkeypatch.setattr(secret_box.settings, "LLM_KEY_ENCRYPTION_SECRET", "")

    with pytest.raises(mail_settings_service.MailSettingsError) as caught:
        mail_settings_service.save({"host": "panel.example.com"}, "app-password")
    assert "LLM_KEY_ENCRYPTION_SECRET" in str(caught.value)


def test_an_undecryptable_password_falls_back_rather_than_raising(store, env_relay, encryptable):
    mail_settings_service.save({"host": "panel.example.com"}, "app-password")
    # Rotating the secret without re-encrypting is a real operational mistake;
    # the relay should degrade to the environment, not throw on every send.
    from cryptography.fernet import Fernet

    with pytest.MonkeyPatch.context() as rotated:
        rotated.setattr(
            secret_box.settings, "LLM_KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode()
        )
        assert mail_settings_service.resolved().password == "env-password"


# ── Writing ─────────────────────────────────────────────────────────────────


def test_an_unknown_field_is_refused(store, env_relay):
    with pytest.raises(mail_settings_service.MailSettingsError):
        mail_settings_service.save({"smtp_host": "typo.example.com"}, None)


def test_clear_falls_back_to_the_environment(store, env_relay, encryptable):
    mail_settings_service.save({"host": "panel.example.com"}, "app-password")
    mail_settings_service.clear()

    assert mail_settings_service.resolved().host == "env.example.com"
    assert mail_settings_service.source() == "env"


def test_clear_keeps_the_signing_secret(store, env_relay, monkeypatch):
    # Otherwise swapping the relay would silently invalidate every address a
    # user had already confirmed.
    monkeypatch.setattr(mail_settings_service.settings, "ALARM_EMAIL_SECRET", "")
    before = mail_settings_service.token_secret()
    mail_settings_service.save({"host": "panel.example.com"}, None)
    mail_settings_service.clear()

    assert mail_settings_service.token_secret() == before


# ── The signing secret ──────────────────────────────────────────────────────


def test_the_environment_secret_wins(store, monkeypatch):
    monkeypatch.setattr(mail_settings_service.settings, "ALARM_EMAIL_SECRET", "from-env")

    assert mail_settings_service.token_secret() == "from-env"


def test_a_secret_is_generated_and_then_kept(store, monkeypatch):
    # This is what lets the whole feature be turned on from the panel without
    # anyone editing a file.
    monkeypatch.setattr(mail_settings_service.settings, "ALARM_EMAIL_SECRET", "")

    first = mail_settings_service.token_secret()
    assert first
    assert mail_settings_service.token_secret() == first


def test_a_corrupt_settings_file_does_not_take_the_relay_down(store, env_relay):
    store.write_text("{ not json")

    assert mail_settings_service.resolved().host == "env.example.com"
