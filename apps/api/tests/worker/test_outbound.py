import threading

import pytest
from sqlalchemy import text

from app.worker.outbound import RetryPolicy, claim_next, recover_interrupted, send_one
from app.worker.provider import PermanentSendError, ProviderError
from tests.worker.conftest import queue, row

POLICY = RetryPolicy(max_attempts=3, backoff_base=2.0)


def run(session_factory, provider, device, sleep):
    return send_one(session_factory, provider, device.id, POLICY, sleep)


def test_nothing_queued_returns_false(session_factory, provider, device, sleep):
    assert run(session_factory, provider, device, sleep) is False


def test_sends_the_oldest_queued_message_first(
    session_factory, commit, ana, provider, device, sleep
):
    first = queue(commit, ana, "first")
    second = queue(commit, ana, "second")
    assert run(session_factory, provider, device, sleep) is True
    assert provider.sent == [("+639171234567", "first")]
    assert row(session_factory, first).status == "sent"
    assert row(session_factory, second).status == "queued"


def test_success_records_status_time_and_device(
    session_factory, commit, ana, provider, device, sleep
):
    mid = queue(commit, ana)
    run(session_factory, provider, device, sleep)
    r = row(session_factory, mid)
    assert (r.status, r.error_message, r.gsm_device_id) == ("sent", None, device.id)
    assert r.sent_at is not None


def test_sends_to_the_snapshot_number_not_the_contacts_current_one(
    session_factory, commit, ana, provider, device, sleep
):
    queue(commit, ana, phone_number="+639189999999")
    run(session_factory, provider, device, sleep)
    assert provider.sent[0][0] == "+639189999999"


def test_only_queued_live_messages_are_claimed(
    session_factory, commit, ana, provider, device, sleep
):
    for status in ("sending", "sent", "failed", "received", "delivered"):
        queue(commit, ana, status=status)
    deleted = queue(commit, ana)
    with session_factory() as db:
        db.execute(text("UPDATE messages SET deleted_at = NOW() WHERE id = :i"), {"i": deleted})
        db.commit()
    assert run(session_factory, provider, device, sleep) is False
    assert provider.sent == []


def test_transient_failures_are_retried_with_exponential_backoff(
    session_factory, commit, ana, provider, device, sleep, sleeps
):
    mid = queue(commit, ana)
    provider.send_errors += [ProviderError("busy"), ProviderError("busy")]
    run(session_factory, provider, device, sleep)
    assert sleeps == [2.0, 4.0]
    r = row(session_factory, mid)
    assert r.status == "sent" and r.error_message is None
    assert len(provider.sent) == 1


def test_gives_up_after_max_attempts(session_factory, commit, ana, provider, device, sleep, sleeps):
    mid = queue(commit, ana)
    provider.send_errors += [ProviderError("no signal")] * 5
    run(session_factory, provider, device, sleep)
    r = row(session_factory, mid)
    assert r.status == "failed" and "no signal" in r.error_message and r.sent_at is None
    assert sleeps == [2.0, 4.0]  # no sleep after the last attempt
    assert len(provider.send_errors) == 2  # exactly 3 attempts consumed


def test_permanent_errors_are_not_retried(
    session_factory, commit, ana, provider, device, sleep, sleeps
):
    mid = queue(commit, ana)
    provider.send_errors.append(PermanentSendError("invalid number"))
    run(session_factory, provider, device, sleep)
    assert row(session_factory, mid).status == "failed" and sleeps == []


def test_unexpected_errors_fail_the_message_and_the_loop_survives(
    session_factory, commit, ana, provider, device, sleep
):
    bad, good = queue(commit, ana, "bad"), queue(commit, ana, "good")
    provider.send_errors.append(RuntimeError("boom"))
    assert run(session_factory, provider, device, sleep) is True
    assert row(session_factory, bad).status == "failed"
    assert "boom" in row(session_factory, bad).error_message
    run(session_factory, provider, device, sleep)
    assert row(session_factory, good).status == "sent"


def test_a_message_deleted_while_sending_still_gets_its_final_status(
    session_factory, commit, ana, provider, device, sleep
):
    mid = queue(commit, ana)

    def delete_during_send(number, content):
        with session_factory() as db:
            db.execute(text("UPDATE messages SET deleted_at = NOW() WHERE id = :i"), {"i": mid})
            db.commit()

    provider.on_send = delete_during_send
    run(session_factory, provider, device, sleep)
    r = row(session_factory, mid)
    assert r.status == "sent" and r.deleted_at is not None


def test_claim_skips_rows_locked_by_another_worker(session_factory, commit, ana, device):
    first, second = queue(commit, ana, "a"), queue(commit, ana, "b")
    with session_factory() as holder, session_factory() as other:
        held = claim_next(holder, device.id, commit=False)
        assert held.id == first  # claimed but not committed: the row stays locked
        taken = claim_next(other, device.id)
        assert taken.id == second  # SKIP LOCKED passes over the locked row
        assert claim_next(other, device.id) is None
        holder.rollback()


def test_concurrent_workers_never_send_the_same_message_twice(
    session_factory, commit, ana, device, sleep
):
    from app.worker.fake import FakeProvider

    ids = [queue(commit, ana, f"m{i}") for i in range(12)]
    providers = [FakeProvider(), FakeProvider()]
    barrier = threading.Barrier(2)

    def drain(provider):
        barrier.wait()
        while send_one(session_factory, provider, device.id, POLICY, sleep):
            pass

    threads = [threading.Thread(target=drain, args=(p,)) for p in providers]
    [t.start() for t in threads]
    [t.join(timeout=30) for t in threads]
    contents = [c for p in providers for _, c in p.sent]
    assert sorted(contents) == sorted(f"m{i}" for i in range(12))  # each exactly once
    assert all(row(session_factory, i).status == "sent" for i in ids)


def test_recover_interrupted_fails_only_this_devices_sending_rows(
    session_factory, commit, ana, device
):
    from app.devices import register_device

    with session_factory() as db:
        other = register_device(db, name="d2", serial_port="/dev/b", phone_number="+639170000002")
    mine = queue(commit, ana, status="sending", gsm_device_id=device.id)
    theirs = queue(commit, ana, status="sending", gsm_device_id=other.id)
    waiting = queue(commit, ana)
    with session_factory() as db:
        assert recover_interrupted(db, device.id) == 1
    r = row(session_factory, mine)
    assert r.status == "failed" and "stopped" in r.error_message
    assert row(session_factory, theirs).status == "sending"
    assert row(session_factory, waiting).status == "queued"
    _ = pytest


def test_a_send_that_keeps_failing_is_recorded_on_the_device(
    session_factory, commit, ana, provider, device, sleep
):
    queue(commit, ana)
    provider.send_errors.extend([ProviderError("no network")] * 3)
    send_one(session_factory, provider, device.id, POLICY, sleep)
    with session_factory() as db:
        error = db.execute(
            text("SELECT last_error FROM gsm_device WHERE id=:i"), {"i": device.id}
        ).scalar_one()
    assert error == "no network"
