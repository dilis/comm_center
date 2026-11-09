import threading
import time
from datetime import datetime

import pytest
from sqlalchemy import text

from app.worker.client import ApiUnavailable
from app.worker.outbound import RetryPolicy
from app.worker.provider import InboundSms, ProviderError
from app.worker.runner import DeviceWorker
from tests.worker.conftest import queue, row

POLICY = RetryPolicy(max_attempts=3, backoff_base=0.0)


def make_worker(api, provider, device, **kw):
    return DeviceWorker(device.id, provider, api, POLICY, sleep=lambda s: None, **kw)


def device_row(session_factory, device):
    with session_factory() as db:
        return db.execute(
            text("SELECT status, last_error, last_error_at FROM gsm_device WHERE id=:i"),
            {"i": device.id},
        ).one()


def test_one_cycle_receives_and_sends_and_marks_the_device_online(
    session_factory, commit, ana, api, provider, device
):
    mid = queue(commit, ana)
    provider.inbound.append(InboundSms("1", "+639171234567", "ping", datetime(2026, 1, 1)))
    worker = make_worker(api, provider, device)
    assert worker.run_once() == 2
    assert row(session_factory, mid).status == "sent"
    with session_factory() as db:
        received = db.execute(text("SELECT COUNT(*) FROM messages WHERE status='received'"))
        assert received.scalar_one() == 1
    assert device_row(session_factory, device).status == "online"
    assert worker.run_once() == 0  # idle


def test_a_modem_error_marks_the_device_error_and_recovers(
    session_factory, commit, ana, api, provider, device
):
    mid = queue(commit, ana)
    provider.poll_errors.append(ProviderError("serial port gone"))
    worker = make_worker(api, provider, device)
    assert worker.run_once() == 0
    assert device_row(session_factory, device).status == "error"
    assert row(session_factory, mid).status == "queued"  # nothing was lost
    worker.run_once()
    assert device_row(session_factory, device).status == "online"
    assert row(session_factory, mid).status == "sent"


def test_a_modem_error_is_kept_on_the_device_for_people_to_see(
    session_factory, api, provider, device
):
    provider.poll_errors.append(ProviderError("serial port gone"))
    worker = make_worker(api, provider, device)
    assert device_row(session_factory, device)[1:] == (None, None)
    worker.run_once()
    row_ = device_row(session_factory, device)
    assert row_.last_error == "serial port gone" and row_.last_error_at is not None
    worker.run_once()  # recovered: the status is online again but the last error stays as history
    row_ = device_row(session_factory, device)
    assert row_.status == "online" and row_.last_error == "serial port gone"


def test_each_cycle_sends_a_bounded_batch_so_inbound_keeps_being_polled(
    session_factory, commit, ana, api, provider, device
):
    ids = [queue(commit, ana, f"m{i}") for i in range(5)]
    worker = make_worker(api, provider, device, max_sends_per_cycle=2)
    assert worker.run_once() == 2
    assert [row(session_factory, i).status for i in ids] == [
        "sent",
        "sent",
        "queued",
        "queued",
        "queued",
    ]


def test_a_busy_queue_does_not_starve_inbound_polling(
    session_factory, commit, ana, api, provider, device
):
    ids = [queue(commit, ana, f"m{i}") for i in range(12)]
    worker = make_worker(api, provider, device)  # the default batch per cycle
    worker.run_once()
    sent = [i for i in ids if row(session_factory, i).status == "sent"]
    assert 0 < len(sent) < 12  # one cycle sends a small batch, then goes back to listen


def test_messages_are_sent_one_at_a_time_each_spending_its_send_time_in_sending(
    session_factory, commit, ana, api, device
):
    """Like a real modem: while one message is being sent the next ones still wait in the queue,
    and the finished ones are already sent. Never all at once."""
    from app.worker.fake import FakeProvider

    ids = [queue(commit, ana, f"m{i}") for i in range(3)]
    seen = []
    provider = FakeProvider(
        send_delay=2.0,
        sleep=lambda seconds: seen.append([row(session_factory, i).status for i in ids]),
    )
    make_worker(api, provider, device).run_once()
    assert seen == [
        ["sending", "queued", "queued"],
        ["sent", "sending", "queued"],
        ["sent", "sent", "sending"],
    ]
    assert [row(session_factory, i).status for i in ids] == ["sent", "sent", "sent"]


def test_an_unreachable_api_raises_so_the_loop_can_wait(api, provider, device, monkeypatch):
    def down(*a, **k):
        raise ApiUnavailable("API unreachable")

    monkeypatch.setattr(api, "inbound", down)
    provider.inbound.append(InboundSms("1", "+639171234567", "ping", datetime(2026, 1, 1)))
    with pytest.raises(ApiUnavailable):
        make_worker(api, provider, device).run_once()
    assert provider.acknowledged == []  # still on the device


def test_run_forever_stops_when_asked_marks_offline_and_closes_the_provider(
    session_factory, commit, ana, api, provider, device
):
    mid = queue(commit, ana)
    beats = []
    stop = threading.Event()
    worker = make_worker(api, provider, device, heartbeat=lambda: beats.append(1))
    thread = threading.Thread(target=worker.run_forever, args=(stop, 0.01))
    thread.start()
    deadline = time.time() + 10
    while row(session_factory, mid).status != "sent" and time.time() < deadline:
        time.sleep(0.02)
    stop.set()
    thread.join(timeout=10)
    assert not thread.is_alive() and beats
    assert row(session_factory, mid).status == "sent"
    assert device_row(session_factory, device).status == "offline" and provider.closed


@pytest.mark.parametrize("error", [RuntimeError("boom"), ApiUnavailable("API unreachable")])
def test_run_forever_survives_an_error(api, provider, device, monkeypatch, error):
    stop = threading.Event()
    worker = make_worker(api, provider, device)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise error
        stop.set()
        return 0

    monkeypatch.setattr(worker, "run_once", flaky)
    worker.run_forever(stop, 0.01)
    assert len(calls) == 2
