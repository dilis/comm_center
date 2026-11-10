import threading
import time

import pytest
from comm_center_worker.client import ApiError, ApiUnavailable
from comm_center_worker.fake import FakeProvider
from comm_center_worker.outbound import RetryPolicy
from comm_center_worker.runner import DeviceWorker
from comm_center_worker.supervisor import Supervisor
from sqlalchemy import text

from app.devices import register_device
from tests.db.helpers import insert
from tests.worker.conftest import queue, row


@pytest.fixture
def build(make_api):
    """A supervisor whose loop gets a fresh API client and a fake provider."""

    def make(unrunnable=False):
        stop = threading.Event()
        made = {}

        def make_worker(device):
            if unrunnable:
                raise ValueError("cannot run this here")
            provider = made.setdefault(device["id"], FakeProvider())
            return DeviceWorker(
                device["id"], provider, make_api(), RetryPolicy(3, 0.0), sleep=lambda s: None
            )

        supervisor = Supervisor(make_api(), make_worker, stop, interval=0.01)
        return supervisor, stop, made

    return make


def shut_down(supervisor, stop):
    stop.set()
    supervisor.stop_all()
    supervisor.join(timeout=10)
    assert not supervisor.running()


def wait_for(condition, timeout=10.0):
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        time.sleep(0.02)
    return condition()


def test_sync_starts_the_loop_for_its_device_and_is_idempotent(build, device):
    supervisor, stop, providers = build()
    assert supervisor.sync() == [device.id]
    assert supervisor.sync() == []  # nothing new, nothing restarted
    assert supervisor.running() == 1
    shut_down(supervisor, stop)
    assert all(p.closed for p in providers.values())


def test_only_the_workers_own_device_is_run(session_factory, build, device):
    with session_factory() as db:
        register_device(db, name="other", phone_number="+639170000004")
    supervisor, stop, _ = build()
    assert supervisor.sync() == [device.id]
    shut_down(supervisor, stop)


def test_the_loops_really_work_the_queue(session_factory, commit, ana, build, device):
    mid = queue(commit, ana)
    supervisor, stop, providers = build()
    supervisor.sync()
    assert wait_for(lambda: row(session_factory, mid).status == "sent")
    shut_down(supervisor, stop)
    assert providers[device.id].sent == [("+639171234567", "hello")]


def test_a_deleted_device_can_no_longer_sign_in_so_the_sync_fails(session_factory, build, device):
    supervisor, stop, _ = build()
    with session_factory() as db:
        db.execute(text("UPDATE gsm_device SET deleted_at = NOW() WHERE id = :i"), {"i": device.id})
        db.commit()
    with pytest.raises(ApiError):
        supervisor.sync()
    shut_down(supervisor, stop)


def test_a_device_this_worker_cannot_run_is_skipped_and_not_retried(build, device):
    supervisor, stop, _ = build(unrunnable=True)
    assert supervisor.sync() == []
    assert supervisor.sync() == []  # not retried (and not logged again) on every sync
    assert supervisor.running() == 0
    shut_down(supervisor, stop)


def test_a_new_session_fails_what_a_crashed_worker_left_sending(
    session_factory, commit, ana, build, device
):
    stuck = queue(commit, ana, status="sending", gsm_device_id=device.id)
    commit(insert, "message_lease", message_id=stuck, device_id=device.id,
           expires_at="2999-01-01 00:00:00")  # fmt: skip
    supervisor, stop, providers = build()
    supervisor.sync()
    assert row(session_factory, stuck).status == "failed"
    shut_down(supervisor, stop)
    assert all(p.sent == [] for p in providers.values())  # never re-sent: it may have gone out


def test_checking_in_during_a_slow_send_does_not_fail_the_message(
    session_factory, commit, ana, build, device, make_api
):
    """The session call is also the heartbeat: it runs every interval, even mid-send."""
    mid = queue(commit, ana)
    supervisor, _, _ = build()
    supervisor._unusable.add(device.id)  # no loop of its own: we drive the cycle by hand
    supervisor.sync()  # the worker starts
    provider = FakeProvider(send_delay=1.0, sleep=lambda s: supervisor.sync())
    DeviceWorker(device.id, provider, make_api(), RetryPolicy(3, 0.0)).run_once()
    assert row(session_factory, mid).status == "sent"


def test_each_supervisor_is_its_own_instance(build):
    first, _, _ = build()
    second, _, _ = build()
    assert first.instance_id and first.instance_id != second.instance_id


def test_run_syncs_beats_and_stops_cleanly(build, device):
    supervisor, stop, providers = build()
    beats = []
    thread = threading.Thread(target=supervisor.run, args=(lambda: beats.append(1),))
    thread.start()
    assert wait_for(lambda: len(beats) >= 2 and supervisor.running() == 1)
    stop.set()
    thread.join(timeout=10)
    assert not thread.is_alive() and providers[device.id].closed


def test_run_keeps_going_but_does_not_beat_while_the_api_is_down(build, monkeypatch):
    supervisor, stop, _ = build()
    calls, beats = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ApiUnavailable("API unreachable")
        stop.set()
        return []

    monkeypatch.setattr(supervisor, "sync", flaky)
    supervisor.run(lambda: beats.append(1))
    assert len(calls) == 3
    assert len(beats) == 1  # only the answer that worked counts as healthy
