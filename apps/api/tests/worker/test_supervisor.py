import threading
import time

import pytest
from comm_center_worker.client import ApiUnavailable
from comm_center_worker.fake import FakeProvider
from comm_center_worker.outbound import RetryPolicy
from comm_center_worker.runner import DeviceWorker
from comm_center_worker.supervisor import Supervisor
from sqlalchemy import text

from app.devices import ensure_fake_device, register_device
from tests.db.helpers import insert
from tests.worker.conftest import queue, row


@pytest.fixture
def build(make_api):
    """A supervisor whose loops each get a fresh API client and a fake provider."""

    def make(providers=None, supported=("fake",)):
        stop = threading.Event()
        made = {} if providers is None else providers

        def make_worker(device):
            if device["provider"] != "fake":
                raise ValueError(f"cannot run {device['provider']}")
            provider = made.setdefault(device["id"], FakeProvider())
            return DeviceWorker(
                device["id"], provider, make_api(), RetryPolicy(3, 0.0), sleep=lambda s: None
            )

        supervisor = Supervisor(make_api(), make_worker, list(supported), stop, interval=0.01)
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


def test_sync_starts_one_loop_per_device_and_is_idempotent(session_factory, build, device):
    supervisor, stop, providers = build()
    with session_factory() as db:
        second = register_device(
            db, name="d2", serial_port="/dev/b", phone_number="+639170000002", worker="w1"
        )
    assert sorted(supervisor.sync()) == sorted([device.id, second.id])
    assert supervisor.sync() == []  # nothing new, nothing restarted
    assert supervisor.running() == 2
    shut_down(supervisor, stop)
    assert all(p.closed for p in providers.values())


def test_only_this_workers_devices_are_run(session_factory, build, device):
    with session_factory() as db:
        register_device(db, name="other", serial_port="/dev/o", phone_number="+639170000004")
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


def test_a_device_assigned_later_is_picked_up_by_the_next_sync(session_factory, build):
    supervisor, stop, _ = build()
    assert supervisor.sync() == []  # nothing assigned yet: idle, not an error
    with session_factory() as db:
        late = register_device(
            db, name="late", serial_port="/dev/l", phone_number="+639170000003", worker="w1"
        )
    assert supervisor.sync() == [late.id]
    shut_down(supervisor, stop)


@pytest.mark.parametrize(
    "removal",
    ["UPDATE gsm_device SET deleted_at = NOW()", "UPDATE gsm_device SET worker_id = NULL"],
)
def test_a_device_taken_away_stops_and_is_not_restarted(session_factory, build, device, removal):
    supervisor, stop, providers = build()
    supervisor.sync()
    with session_factory() as db:
        db.execute(text(removal + " WHERE id = :i"), {"i": device.id})
        db.commit()
    assert supervisor.sync() == []
    assert wait_for(lambda: supervisor.running() == 0)
    assert providers[device.id].closed
    assert supervisor.sync() == []
    shut_down(supervisor, stop)


def test_a_device_this_worker_cannot_run_is_skipped_without_harming_the_others(
    session_factory, build, device
):
    with session_factory() as db:
        register_device(
            db, name="modem", serial_port="/dev/m", phone_number="+639170000005",
            provider="gsm_modem", worker="w1",
        )  # fmt: skip
    supervisor, stop, _ = build()
    assert supervisor.sync() == [device.id]
    assert supervisor.sync() == []  # not retried (and not logged again) on every sync
    shut_down(supervisor, stop)


def test_the_session_reports_the_providers_this_worker_supports(build, monkeypatch):
    supervisor, stop, _ = build(supported=("fake", "android"))
    seen = {}
    real = supervisor.api.session

    def spy(version, providers, instance_id, protocol_version=1):
        seen["providers"] = providers
        return real(version, providers, instance_id, protocol_version)

    monkeypatch.setattr(supervisor.api, "session", spy)
    supervisor.sync()
    assert seen["providers"] == ["fake", "android"]
    shut_down(supervisor, stop)


def test_a_new_session_fails_what_a_crashed_worker_left_sending(
    session_factory, commit, ana, build, device, worker
):
    account, _ = worker
    stuck = queue(commit, ana, status="sending", gsm_device_id=device.id)
    commit(insert, "message_lease", message_id=stuck, worker_id=account.id, device_id=device.id,
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


def test_ensure_fake_device_registers_one_only_when_there_is_none(session_factory, worker):
    with session_factory() as db:
        created = ensure_fake_device(db, "w1")
    assert created is not None and created.name == "fake"
    with session_factory() as db:
        assert ensure_fake_device(db, "w1") is None  # already has a device
        assert db.execute(text("SELECT COUNT(*) FROM gsm_device")).scalar_one() == 1


def test_ensure_fake_device_leaves_real_devices_alone(session_factory, device):
    with session_factory() as db:
        assert ensure_fake_device(db, "w1") is None
        assert db.execute(text("SELECT name FROM gsm_device")).scalars().all() == ["d1"]
