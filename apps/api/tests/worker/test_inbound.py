from datetime import datetime

import pytest
from sqlalchemy import text

from app.worker.client import ApiError, ApiUnavailable
from app.worker.fake import FakeProvider
from app.worker.inbound import process_inbound
from app.worker.provider import InboundSms


def sms(sender="+639171234567", content="hi", ref="1"):
    return InboundSms(
        ref=ref, sender=sender, content=content, received_at=datetime(2026, 1, 2, 3, 4, 5)
    )


def q(session_factory, sql, **params):
    with session_factory() as db:
        return db.execute(text(sql), params).all()


def test_unparseable_sender_is_dropped_and_acknowledged(session_factory, api, provider, device):
    provider.inbound.append(sms(sender="GLOBE", content="promo"))
    provider.inbound.append(sms(sender="+639171234567", content="real", ref="2"))
    assert process_inbound(api, provider, device.id) == 1
    assert [m.content for m in q(session_factory, "SELECT content FROM messages")] == ["real"]
    assert [s.ref for s in provider.acknowledged] == ["1", "2"]  # nothing left to re-poll


def test_messages_are_acknowledged_only_after_they_are_committed(
    session_factory, api, provider, device
):
    provider.inbound.append(sms(content="durable"))
    seen = []
    provider.on_acknowledge = lambda s: seen.append(
        q(session_factory, "SELECT content FROM messages WHERE content='durable'")
    )
    process_inbound(api, provider, device.id)
    assert len(seen) == 1 and len(seen[0]) == 1


def test_a_message_the_api_refuses_is_not_acknowledged_so_it_is_polled_again(
    api, provider, device, monkeypatch
):
    provider.inbound.append(sms(content="x"))

    def refuse(device_id, message):
        raise ApiError("refused", 422)

    monkeypatch.setattr(api, "inbound", refuse)
    process_inbound(api, provider, device.id)
    assert provider.acknowledged == []
    assert [s.content for s in provider.poll_inbound()] == ["x"]  # still there next cycle


def test_an_unreachable_api_leaves_everything_on_the_device(api, provider, device, monkeypatch):
    provider.inbound.extend([sms(ref="1"), sms(ref="2")])

    def down(device_id, message):
        raise ApiUnavailable("API unreachable")

    monkeypatch.setattr(api, "inbound", down)
    with pytest.raises(ApiUnavailable):
        process_inbound(api, provider, device.id)
    assert provider.acknowledged == []


def test_a_message_redelivered_after_a_crash_is_stored_once_and_acknowledged(
    session_factory, api, device
):
    """The worker died after the API stored it but before it forgot it on the device."""
    first, second = FakeProvider(), FakeProvider()
    first.inbound.append(sms(content="once"))
    second.inbound.append(sms(content="once"))  # the same message, offered again
    assert process_inbound(api, first, device.id) == 1
    assert process_inbound(api, second, device.id) == 0  # a duplicate: not stored again
    assert [s.ref for s in second.acknowledged] == ["1"]  # but now it can be forgotten
    assert q(session_factory, "SELECT COUNT(*) AS n FROM messages WHERE content='once'")[0].n == 1
