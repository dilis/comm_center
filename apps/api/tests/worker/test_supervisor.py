import threading
import time

from sqlalchemy import text

from app.devices import ensure_fake_device, register_device
from app.worker.fake import FakeProvider
from app.worker.outbound import RetryPolicy
from app.worker.runner import DeviceWorker
from app.worker.supervisor import Supervisor
from tests.worker.conftest import queue, row


def make_supervisor(session_factory, providers=None):
    stop = threading.Event()
    providers = {} if providers is None else providers

    def make_worker(device_id):
        provider = providers.setdefault(device_id, FakeProvider())
        return DeviceWorker(
            device_id, provider, session_factory, RetryPolicy(3, 0.0), sleep=lambda s: None
        )

    return Supervisor(session_factory, make_worker, stop, interval=0.01), stop, providers


def shut_down(supervisor, stop):
    stop.set()
    supervisor.join(timeout=10)
    assert not supervisor.running()


def wait_for(condition, timeout=10.0):
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        time.sleep(0.02)
    return condition()


def test_sync_starts_one_loop_per_device_and_is_idempotent(session_factory, device):
    supervisor, stop, providers = make_supervisor(session_factory)
    with session_factory() as db:
        second = register_device(db, name="d2", serial_port="/dev/b", phone_number="+639170000002")
    assert sorted(supervisor.sync()) == sorted([device.id, second.id])
    assert supervisor.sync() == []  # nothing new, nothing restarted
    assert supervisor.running() == 2
    shut_down(supervisor, stop)
    assert all(p.closed for p in providers.values())


def test_the_loops_really_work_the_queue(session_factory, commit, ana, device):
    mid = queue(commit, ana)
    supervisor, stop, providers = make_supervisor(session_factory)
    supervisor.sync()
    assert wait_for(lambda: row(session_factory, mid).status == "sent")
    shut_down(supervisor, stop)
    assert providers[device.id].sent == [("+639171234567", "hello")]


def test_a_device_registered_later_is_picked_up_by_the_next_sync(session_factory):
    supervisor, stop, _ = make_supervisor(session_factory)
    assert supervisor.sync() == []  # nothing registered yet: idle, not an error
    with session_factory() as db:
        late = register_device(db, name="late", serial_port="/dev/l", phone_number="+639170000003")
    assert supervisor.sync() == [late.id]
    shut_down(supervisor, stop)


def test_a_removed_device_stops_and_is_not_restarted(session_factory, device):
    supervisor, stop, _ = make_supervisor(session_factory)
    supervisor.sync()
    with session_factory() as db:
        db.execute(text("UPDATE gsm_device SET deleted_at = NOW() WHERE id = :i"), {"i": device.id})
        db.commit()
    assert wait_for(lambda: supervisor.running() == 0)
    assert supervisor.sync() == []
    shut_down(supervisor, stop)


def test_run_syncs_beats_and_stops_cleanly(session_factory, device):
    supervisor, stop, providers = make_supervisor(session_factory)
    beats = []
    thread = threading.Thread(target=supervisor.run, args=(lambda: beats.append(1),))
    thread.start()
    assert wait_for(lambda: len(beats) >= 2 and supervisor.running() == 1)
    stop.set()
    thread.join(timeout=10)
    assert not thread.is_alive() and providers[device.id].closed


def test_run_keeps_going_when_the_database_blips(session_factory, monkeypatch):
    supervisor, stop, _ = make_supervisor(session_factory)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database went away")
        stop.set()
        return []

    monkeypatch.setattr(supervisor, "sync", flaky)
    supervisor.run(lambda: None)
    assert len(calls) == 2


def test_ensure_fake_device_registers_one_only_when_there_is_none(session_factory):
    with session_factory() as db:
        created = ensure_fake_device(db)
    assert created is not None and created.name == "fake"
    with session_factory() as db:
        assert ensure_fake_device(db) is None  # already has a device
        assert db.execute(text("SELECT COUNT(*) FROM gsm_device")).scalar_one() == 1


def test_ensure_fake_device_leaves_real_devices_alone(session_factory, device):
    with session_factory() as db:
        assert ensure_fake_device(db) is None
        assert db.execute(text("SELECT name FROM gsm_device")).scalars().all() == ["d1"]
