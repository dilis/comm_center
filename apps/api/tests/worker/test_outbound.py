import threading

import pytest
from sqlalchemy import text

from app.worker.client import ApiClient, ApiUnavailable
from app.worker.outbound import RetryPolicy, send_one
from app.worker.provider import PermanentSendError, ProviderError
from tests.worker.conftest import queue, row

POLICY = RetryPolicy(max_attempts=3, backoff_base=2.0)


def run(api, provider, device, sleep):
    return send_one(api, provider, device.id, POLICY, sleep)


def test_nothing_queued_returns_false(api, provider, device, sleep):
    assert run(api, provider, device, sleep) is False


def test_sends_the_oldest_queued_message_first(
    session_factory, commit, ana, api, provider, device, sleep
):
    first = queue(commit, ana, "first")
    second = queue(commit, ana, "second")
    assert run(api, provider, device, sleep) is True
    assert provider.sent == [("+639171234567", "first")]
    assert row(session_factory, first).status == "sent"
    assert row(session_factory, second).status == "queued"


def test_success_records_status_time_and_device(
    session_factory, commit, ana, api, provider, device, sleep
):
    mid = queue(commit, ana)
    run(api, provider, device, sleep)
    r = row(session_factory, mid)
    assert (r.status, r.error_message, r.gsm_device_id) == ("sent", None, device.id)
    assert r.sent_at is not None


def test_sends_to_the_snapshot_number_not_the_contacts_current_one(
    commit, ana, api, provider, device, sleep
):
    queue(commit, ana, phone_number="+639189999999")
    run(api, provider, device, sleep)
    assert provider.sent[0][0] == "+639189999999"


def test_only_queued_live_messages_are_claimed(
    session_factory, commit, ana, api, provider, device, sleep
):
    for status in ("sending", "sent", "failed", "received", "delivered"):
        queue(commit, ana, status=status)
    deleted = queue(commit, ana)
    with session_factory() as db:
        db.execute(text("UPDATE messages SET deleted_at = NOW() WHERE id = :i"), {"i": deleted})
        db.commit()
    assert run(api, provider, device, sleep) is False
    assert provider.sent == []


def test_transient_failures_are_retried_with_exponential_backoff(
    session_factory, commit, ana, api, provider, device, sleep, sleeps
):
    mid = queue(commit, ana)
    provider.send_errors += [ProviderError("busy"), ProviderError("busy")]
    run(api, provider, device, sleep)
    assert sleeps == [2.0, 4.0]
    r = row(session_factory, mid)
    assert r.status == "sent" and r.error_message is None
    assert len(provider.sent) == 1


def test_the_lease_is_extended_between_retries(
    commit, ana, api, provider, device, sleep, monkeypatch
):
    queue(commit, ana)
    provider.send_errors += [ProviderError("busy")] * 2
    extended = []
    real = api.extend
    monkeypatch.setattr(api, "extend", lambda mid: (extended.append(mid), real(mid)))
    run(api, provider, device, sleep)
    assert len(extended) == 2


def test_gives_up_after_max_attempts(
    session_factory, commit, ana, api, provider, device, sleep, sleeps
):
    mid = queue(commit, ana)
    provider.send_errors += [ProviderError("no signal")] * 5
    run(api, provider, device, sleep)
    r = row(session_factory, mid)
    assert r.status == "failed" and "no signal" in r.error_message and r.sent_at is None
    assert sleeps == [2.0, 4.0]  # no sleep after the last attempt
    assert len(provider.send_errors) == 2  # exactly 3 attempts consumed


def test_permanent_errors_are_not_retried(
    session_factory, commit, ana, api, provider, device, sleep, sleeps
):
    mid = queue(commit, ana)
    provider.send_errors.append(PermanentSendError("invalid number"))
    run(api, provider, device, sleep)
    assert row(session_factory, mid).status == "failed" and sleeps == []


def test_unexpected_errors_fail_the_message_and_the_loop_survives(
    session_factory, commit, ana, api, provider, device, sleep
):
    bad, good = queue(commit, ana, "bad"), queue(commit, ana, "good")
    provider.send_errors.append(RuntimeError("boom"))
    assert run(api, provider, device, sleep) is True
    assert row(session_factory, bad).status == "failed"
    assert "boom" in row(session_factory, bad).error_message
    run(api, provider, device, sleep)
    assert row(session_factory, good).status == "sent"


def test_a_message_deleted_while_sending_still_gets_its_final_status(
    session_factory, commit, ana, api, provider, device, sleep
):
    mid = queue(commit, ana)

    def delete_during_send(number, content):
        with session_factory() as db:
            db.execute(text("UPDATE messages SET deleted_at = NOW() WHERE id = :i"), {"i": mid})
            db.commit()

    provider.on_send = delete_during_send
    run(api, provider, device, sleep)
    r = row(session_factory, mid)
    assert r.status == "sent" and r.deleted_at is not None


def test_a_send_that_keeps_failing_is_recorded_on_the_device(
    session_factory, commit, ana, api, provider, device, sleep
):
    queue(commit, ana)
    provider.send_errors.extend([ProviderError("no network")] * 3)
    send_one(api, provider, device.id, POLICY, sleep)
    with session_factory() as db:
        error = db.execute(
            text("SELECT last_error FROM gsm_device WHERE id=:i"), {"i": device.id}
        ).scalar_one()
    assert error == "no network"


def test_an_unreachable_api_stops_the_claim_and_loses_nothing(
    session_factory, commit, ana, api, provider, device, sleep, monkeypatch
):
    mid = queue(commit, ana)

    def down(*args, **kwargs):
        raise ApiUnavailable("API unreachable")

    monkeypatch.setattr(api, "claim", down)
    with pytest.raises(ApiUnavailable):
        run(api, provider, device, sleep)
    assert provider.sent == [] and row(session_factory, mid).status == "queued"


def test_a_result_that_cannot_be_reported_is_retried_then_left_to_the_lease(
    session_factory, commit, ana, api, provider, device, sleep, sleeps, monkeypatch
):
    mid = queue(commit, ana)
    attempts = []

    def down(*args, **kwargs):
        attempts.append(1)
        raise ApiUnavailable("API unreachable")

    monkeypatch.setattr(api, "result", down)
    assert run(api, provider, device, sleep) is True
    assert len(provider.sent) == 1 and len(attempts) == 3  # the SMS went; telling the API failed
    assert sleeps == [2.0, 4.0]
    assert row(session_factory, mid).status == "sending"  # the lease will fail it, never re-send


def test_concurrent_workers_never_send_the_same_message_twice(
    session_factory, commit, ana, make_api, device, sleep
):
    from app.worker.fake import FakeProvider

    ids = [queue(commit, ana, f"m{i}") for i in range(30)]
    providers = [FakeProvider(), FakeProvider()]
    apis: list[ApiClient] = [make_api(), make_api()]
    barrier = threading.Barrier(2)

    errors = []

    def drain(provider, api):
        barrier.wait()
        try:
            while send_one(api, provider, device.id, POLICY, sleep):
                pass
        except Exception as exc:  # noqa: BLE001 - a dead thread must fail the test
            errors.append(exc)

    threads = [threading.Thread(target=drain, args=(p, a)) for p, a in zip(providers, apis)]
    [t.start() for t in threads]
    [t.join(timeout=60) for t in threads]
    assert errors == []
    contents = [c for p in providers for _, c in p.sent]
    assert sorted(contents) == sorted(f"m{i}" for i in range(30))  # each exactly once
    assert all(row(session_factory, i).status == "sent" for i in ids)
