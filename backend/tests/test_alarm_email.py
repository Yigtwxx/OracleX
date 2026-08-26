"""
Alarm mail: the confirmation handshake, the token, and what the relay is handed.

Nothing here opens a socket. `email_delivery.send_html` is replaced by a recorder
in every test that would send, which is what lets the interesting assertions —
that a wrong code is refused, that a token does not travel between addresses,
that the message carries a plaintext part and an unsubscribe header — run in
milliseconds against no network.
"""

import pytest

from services import alarm_email_service, email_delivery, mail_settings_service
from services.alarm_email_service import AlarmMailPayload, TooManyRequests


@pytest.fixture
def relay(monkeypatch, tmp_path):
    """
    A configured relay that records instead of sending.

    Yields the list of messages, so a test reads what would have gone out. The
    settings store is redirected into `tmp_path` so nothing here can read or
    write a developer's real `backend/data/mail_settings.json`.
    """
    monkeypatch.setattr(mail_settings_service, "_STORE_PATH", str(tmp_path / "mail_settings.json"))
    monkeypatch.setattr(
        mail_settings_service,
        "resolved",
        lambda: mail_settings_service.MailSettings(
            host="smtp.example.com",
            port=587,
            user="alerts@example.com",
            password="secret",
            ssl=False,
            starttls=True,
            from_address="",
            from_name="Oracle-X",
            reply_to="",
        ),
    )

    sent: list[dict] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(email_delivery, "send_html", fake_send)
    # `check_deliverable` would resolve MX over the network; the guard has its
    # own tests and this one is not about addresses.
    monkeypatch.setattr(
        alarm_email_service.email_guard,
        "check_deliverable",
        _always_deliverable,
    )
    alarm_email_service.reset_state()
    yield sent
    alarm_email_service.reset_state()


async def _always_deliverable(email: str):
    from services.email_guard import EmailVerdict

    return EmailVerdict(ok=True, reason="ok", message="", domain="example.com")


def _code_from(sent: list[dict]) -> str:
    """The six digits the confirmation mail carried, read out of its text part."""
    import re

    match = re.search(r"\b(\d{6})\b", sent[-1]["text"])
    assert match, "confirmation mail carried no six-digit code"
    return match.group(1)


# ── The confirmation handshake ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_code_mails_a_six_digit_code(relay):
    await alarm_email_service.request_code("reader@example.com")

    assert len(relay) == 1, "exactly one confirmation mail should be sent"
    assert relay[0]["to"] == "reader@example.com"
    assert len(_code_from(relay)) == 6


@pytest.mark.asyncio
async def test_confirmation_code_is_absent_from_the_subject(relay):
    # It would show on a lock screen, and this code binds an address to a
    # notification channel that afterwards needs no further proof.
    await alarm_email_service.request_code("reader@example.com")

    code = _code_from(relay)
    assert code not in relay[0]["subject"], "the code must not travel in the subject line"


@pytest.mark.asyncio
async def test_correct_code_yields_a_working_token(relay):
    await alarm_email_service.request_code("reader@example.com")
    token = alarm_email_service.confirm_code("reader@example.com", _code_from(relay))

    assert alarm_email_service.token_valid("reader@example.com", token)


@pytest.mark.asyncio
async def test_wrong_code_is_refused_and_says_how_many_tries_remain(relay):
    await alarm_email_service.request_code("reader@example.com")

    with pytest.raises(alarm_email_service.AlarmEmailError) as caught:
        alarm_email_service.confirm_code("reader@example.com", "000000")
    assert "attempts left" in str(caught.value)


@pytest.mark.asyncio
async def test_a_code_can_only_be_confirmed_once(relay):
    await alarm_email_service.request_code("reader@example.com")
    code = _code_from(relay)
    alarm_email_service.confirm_code("reader@example.com", code)

    # The second attempt must not succeed just because the digits still match.
    with pytest.raises(alarm_email_service.AlarmEmailError):
        alarm_email_service.confirm_code("reader@example.com", code)


@pytest.mark.asyncio
async def test_guessing_is_capped_then_the_code_is_burned(relay):
    await alarm_email_service.request_code("reader@example.com")

    for _ in range(5):
        with pytest.raises(alarm_email_service.AlarmEmailError):
            alarm_email_service.confirm_code("reader@example.com", "000000")

    with pytest.raises(TooManyRequests):
        alarm_email_service.confirm_code("reader@example.com", "000000")


@pytest.mark.asyncio
async def test_repeated_code_requests_are_throttled_per_address(relay):
    for _ in range(3):
        await alarm_email_service.request_code("reader@example.com")

    with pytest.raises(TooManyRequests):
        await alarm_email_service.request_code("reader@example.com")


# ── The token ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_token_does_not_work_for_another_address(relay):
    # The whole security property: possession of a token proves that *this*
    # address confirmed, and says nothing about any other.
    await alarm_email_service.request_code("reader@example.com")
    token = alarm_email_service.confirm_code("reader@example.com", _code_from(relay))

    assert not alarm_email_service.token_valid("someone.else@example.com", token)


def test_an_empty_token_is_never_valid(relay):
    assert not alarm_email_service.token_valid("reader@example.com", "")


@pytest.mark.asyncio
async def test_send_alarm_refuses_a_token_this_backend_did_not_issue(relay):
    with pytest.raises(alarm_email_service.AlarmEmailError):
        await alarm_email_service.send_alarm("reader@example.com", "not-a-real-token", _payload())
    assert relay == [], "nothing may be sent on a bad token"


# ── Sending ─────────────────────────────────────────────────────────────────


def _payload(event_id: str = "e1") -> AlarmMailPayload:
    return AlarmMailPayload(
        event_id=event_id,
        source_label="Price",
        subject_line="BTCUSDT · Price",
        observed="$72,450.00",
        rule="price rises above $70,000.00",
        fired_at_label="25 August 2026, 02:32 PM",
        tone="up",
        trigger_count=3,
    )


async def _confirmed(relay) -> str:
    """Walk one address through the handshake and hand back its token."""
    await alarm_email_service.request_code("reader@example.com")
    return alarm_email_service.confirm_code("reader@example.com", _code_from(relay))


@pytest.mark.asyncio
async def test_a_repeated_event_id_is_delivered_only_once(relay):
    token = await _confirmed(relay)
    relay.clear()

    assert await alarm_email_service.send_alarm("reader@example.com", token, _payload())
    assert not await alarm_email_service.send_alarm("reader@example.com", token, _payload())
    assert len(relay) == 1, "the browser retrying must not mail the reader twice"


@pytest.mark.asyncio
async def test_distinct_events_both_go_out(relay):
    token = await _confirmed(relay)
    relay.clear()

    await alarm_email_service.send_alarm("reader@example.com", token, _payload("e1"))
    await alarm_email_service.send_alarm("reader@example.com", token, _payload("e2"))
    assert len(relay) == 2


@pytest.mark.asyncio
async def test_the_hourly_cap_stops_a_runaway_alarm(relay, monkeypatch):
    monkeypatch.setattr(alarm_email_service.settings, "ALARM_EMAIL_HOURLY_LIMIT", 2)
    token = await _confirmed(relay)
    relay.clear()

    await alarm_email_service.send_alarm("reader@example.com", token, _payload("e1"))
    await alarm_email_service.send_alarm("reader@example.com", token, _payload("e2"))
    with pytest.raises(TooManyRequests):
        await alarm_email_service.send_alarm("reader@example.com", token, _payload("e3"))


@pytest.mark.asyncio
async def test_alarm_mail_leads_with_the_reading(relay):
    token = await _confirmed(relay)
    relay.clear()
    await alarm_email_service.send_alarm("reader@example.com", token, _payload())

    message = relay[0]
    # The value is why the reader opened the mail; the rule is context they wrote
    # themselves. That ordering is the whole design of the template.
    assert "$72,450.00" in message["subject"]
    assert message["subject"].index("BTCUSDT") < message["subject"].index("$72,450.00")


@pytest.mark.asyncio
async def test_alarm_mail_carries_a_plaintext_part_and_an_unsubscribe_address(relay):
    # Both are deliverability, not decoration: an HTML-only body is one of the
    # oldest spam signals there is, and List-Unsubscribe is what Gmail and Yahoo
    # have expected since 2024.
    token = await _confirmed(relay)
    relay.clear()
    await alarm_email_service.send_alarm("reader@example.com", token, _payload())

    message = relay[0]
    assert "$72,450.00" in message["text"]
    assert "price rises above $70,000.00" in message["text"]
    assert message["unsubscribe_mailto"]


@pytest.mark.asyncio
async def test_caller_supplied_html_is_escaped_not_rendered(relay):
    token = await _confirmed(relay)
    relay.clear()
    await alarm_email_service.send_alarm(
        "reader@example.com",
        token,
        AlarmMailPayload(
            event_id="xss",
            source_label="Price",
            subject_line="<script>alert(1)</script>",
            observed="$1.00",
            rule="rule",
            fired_at_label="now",
        ),
    )

    html = relay[0]["html"]
    assert "<script>" not in html, "a request must never reach the template as markup"
    assert "&lt;script&gt;" in html


# ── Composition, without a relay ────────────────────────────────────────────


def test_render_alarm_clips_an_overlong_field():
    subject, html, text = alarm_email_service.render_alarm(
        AlarmMailPayload(
            event_id="e1",
            source_label="Price",
            subject_line="x" * 500,
            observed="$1.00",
            rule="rule",
            fired_at_label="now",
        )
    )
    assert "x" * 201 not in subject
    assert "x" * 201 not in html
    assert "x" * 201 not in text


def test_render_alarm_omits_the_trigger_count_on_a_first_fire():
    _, html, _ = alarm_email_service.render_alarm(
        AlarmMailPayload(
            event_id="e1",
            source_label="Price",
            subject_line="BTCUSDT · Price",
            observed="$1.00",
            rule="rule",
            fired_at_label="now",
            trigger_count=1,
        )
    )
    assert "Times fired" not in html, "'fired once' is noise, not provenance"


@pytest.mark.parametrize(
    "tone,colour",
    [("up", "#22c55e"), ("down", "#ef4444"), ("warn", "#f59e0b"), ("accent", "#2f6feb")],
)
def test_tone_paints_the_template(tone, colour):
    _, html, _ = alarm_email_service.render_alarm(
        AlarmMailPayload(
            event_id="e1",
            source_label="Price",
            subject_line="BTCUSDT · Price",
            observed="$1.00",
            rule="rule",
            fired_at_label="now",
            tone=tone,
        )
    )
    assert colour in html
