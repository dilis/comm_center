"""The worker's loops against an in-memory API: retries, reporting, acknowledging, supervising."""

import threading
import time
from datetime import datetime

import httpx
import pytest

from comm_center_worker.client import ApiClient, ApiUnavailable
from comm_center_worker.fake import FakeProvider
from comm_center_worker.inbound import process_inbound
from comm_center_worker.outbound import RetryPolicy, send_one
from comm_center_worker.provider import InboundSms, PermanentSendError, ProviderError
from comm_center_worker.runner import DeviceWorker
from comm_center_worker.supervisor import Supervisor
from tests.fake_server import FakeServer

POLICY = RetryPolicy(max_attempts=3, backoff_base=2.0)


@pytest.fixture
def server():
    return FakeServer()


def make_api(server) -> ApiClient:
    return ApiClient(httpx.Client(base_url="http://api", transport=server.transport()), "w1", "s")


@pytest.fixture
def api(server):
    return make_api(server)


@pytest.fixture
def sleeps():
    return []


def message(i=1, content="hello"):
    return {"id": i, "phone_number": "+639171234567", "content": content}


def sms(ref="1", sender="+639171234567"):
    return InboundSms(ref, sender, "hi", datetime(2026, 1, 2, 3, 4, 5))


# --- outbound ---


def test_a_queued_message_is_sent_and_reported(server, api, sleeps):
    server.queue.append(message())
    provider = FakeProvider()
    assert send_one(api, provider, 3, POLICY, sleeps.append) is True
    assert provider.sent == [("+639171234567", "hello")]
    assert server.results == [(1, "sent", None)]


def test_an_empty_queue_returns_false(api, sleeps):
    assert send_one(api, FakeProvider(), 3, POLICY, sleeps.append) is False


def test_transient_failures_retry_with_backoff_and_keep_the_lease(server, api, sleeps):
    server.queue.append(message())
    provider = FakeProvider()
    provider.send_errors += [ProviderError("busy"), ProviderError("busy")]
    send_one(api, provider, 3, POLICY, sleeps.append)
    assert sleeps == [2.0, 4.0] and server.extended == [1, 1]
    assert server.results == [(1, "sent", None)]


def test_giving_up_reports_the_failure_and_the_device_error(server, api, sleeps):
    server.queue.append(message())
    provider = FakeProvider()
    provider.send_errors += [ProviderError("no signal")] * 3
    send_one(api, provider, 3, POLICY, sleeps.append)
    assert server.results == [(1, "failed", "no signal")]
    assert server.statuses == [(3, "error", "no signal")]


def test_a_permanent_rejection_is_not_retried(server, api, sleeps):
    server.queue.append(message())
    provider = FakeProvider()
    provider.send_errors.append(PermanentSendError("invalid number"))
    send_one(api, provider, 3, POLICY, sleeps.append)
    assert server.results == [(1, "failed", "invalid number")] and sleeps == []


def test_an_unexpected_error_is_reported_and_the_loop_continues(server, api, sleeps):
    server.queue += [message(1, "bad"), message(2, "good")]
    provider = FakeProvider()
    provider.send_errors.append(RuntimeError("boom"))
    assert send_one(api, provider, 3, POLICY, sleeps.append) is True
    assert server.results[0][:2] == (1, "failed") and "boom" in server.results[0][2]
    send_one(api, provider, 3, POLICY, sleeps.append)
    assert server.results[1] == (2, "sent", None)


def test_a_result_that_cannot_be_delivered_is_retried_then_left_to_the_lease(server, api, sleeps):
    server.queue.append(message())
    server.fail["/worker/messages/1/result"] = [503, 503, 503]
    provider = FakeProvider()
    assert send_one(api, provider, 3, POLICY, sleeps.append) is True
    assert len(provider.sent) == 1 and server.results == [] and sleeps == [2.0, 4.0]


def test_a_conflict_on_the_result_is_not_retried(server, api, sleeps):
    server.queue.append(message())
    server.fail["/worker/messages/1/result"] = [409]
    send_one(api, FakeProvider(), 3, POLICY, sleeps.append)
    assert sleeps == [] and server.results == []


def test_an_unreachable_api_stops_the_claim(server, api, sleeps):
    server.fail["/worker/claim"] = [503]
    with pytest.raises(ApiUnavailable):
        send_one(api, FakeProvider(), 3, POLICY, sleeps.append)


# --- inbound ---


def test_a_message_is_acknowledged_only_after_the_api_took_it(server, api):
    provider = FakeProvider()
    provider.inbound.append(sms())
    seen_by_server_at_ack = []
    provider.on_acknowledge = lambda s: seen_by_server_at_ack.append(len(server.inbound))
    assert process_inbound(api, provider, 3) == 1
    assert seen_by_server_at_ack == [1]


def test_a_duplicate_is_acknowledged_but_not_counted(server, api):
    first, second = FakeProvider(), FakeProvider()
    first.inbound.append(sms())
    second.inbound.append(sms())  # offered again after a crash
    process_inbound(api, first, 3)
    assert process_inbound(api, second, 3) == 0
    assert len(second.acknowledged) == 1 and len(server.inbound) == 1


def test_nothing_is_acknowledged_while_the_api_is_down(server, api):
    provider = FakeProvider()
    provider.inbound += [sms("1"), sms("2")]
    server.fail["/worker/inbound"] = [503]
    with pytest.raises(ApiUnavailable):
        process_inbound(api, provider, 3)
    assert provider.acknowledged == []


def test_a_message_the_api_refuses_stays_on_the_device(server, api):
    provider = FakeProvider()
    provider.inbound.append(sms())
    server.fail["/worker/inbound"] = [422]
    process_inbound(api, provider, 3)
    assert provider.acknowledged == []


# --- the device loop ---


def worker(api, provider, **kw):
    return DeviceWorker(3, provider, api, RetryPolicy(3, 0.0), sleep=lambda s: None, **kw)


def test_a_cycle_receives_sends_and_marks_the_device_online(server, api):
    server.queue.append(message())
    provider = FakeProvider()
    provider.inbound.append(sms())
    assert worker(api, provider).run_once() == 2
    assert server.statuses == [(3, "online", None)] and server.results == [(1, "sent", None)]
    assert worker(api, provider).run_once() == 0


def test_a_device_error_is_reported_and_nothing_is_lost(server, api):
    server.queue.append(message())
    provider = FakeProvider()
    provider.poll_errors.append(ProviderError("serial port gone"))
    w = worker(api, provider)
    assert w.run_once() == 0
    assert server.statuses == [(3, "error", "serial port gone")] and server.queue
    w.run_once()
    assert server.statuses[-1] == (3, "online", None) and server.results == [(1, "sent", None)]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_sends_are_spaced_by_the_send_interval(server, api):
    server.queue += [message(i) for i in range(1, 4)]
    clock = Clock()
    w = worker(api, FakeProvider(), send_interval=30, clock=clock)
    assert w.run_once() == 1  # the first goes at once, one per cycle
    assert w.run_once() == 0 and len(server.results) == 1  # too soon: nothing is even claimed
    assert len(server.queue) == 2
    clock.now += 29
    assert w.run_once() == 0 and len(server.results) == 1
    clock.now += 1
    assert w.run_once() == 1 and len(server.results) == 2


def test_the_wait_is_counted_from_the_end_of_the_previous_send(server, api):
    server.queue += [message(1), message(2)]
    clock = Clock()

    class Slow(FakeProvider):
        def send(self, *a, **kw):
            clock.now += 8  # the send itself takes time
            super().send(*a, **kw)

    w = worker(api, Slow(), send_interval=10, clock=clock)
    w.run_once()
    clock.now += 9
    assert w.run_once() == 0
    clock.now += 1
    assert w.run_once() == 1


def test_a_throttled_worker_still_receives(server, api):
    server.queue += [message(1), message(2)]
    provider = FakeProvider()
    w = worker(api, provider, send_interval=30, clock=Clock())
    w.run_once()
    provider.inbound.append(sms())
    assert w.run_once() == 1 and len(server.results) == 1  # received, did not send


def test_no_interval_means_no_spacing(server, api):
    server.queue += [message(i) for i in range(1, 4)]
    assert worker(api, FakeProvider(), send_interval=0, clock=Clock()).run_once() == 3


def test_a_cycle_sends_a_bounded_batch(server, api):
    server.queue += [message(i) for i in range(1, 6)]
    assert worker(api, FakeProvider(), max_sends_per_cycle=2).run_once() == 2
    assert len(server.queue) == 3


def test_the_loop_survives_errors_and_goes_offline_when_stopped(server, api):
    provider = FakeProvider()
    stop = threading.Event()
    w = worker(api, provider)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise ApiUnavailable("down")
        stop.set()
        return 0

    w.run_once = flaky
    w.run_forever(stop, 0.01)
    assert len(calls) == 2 and provider.closed and server.statuses[-1] == (3, "offline", None)


# --- the supervisor ---


def wait_for(condition, timeout=10.0):
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        time.sleep(0.02)
    return condition()


@pytest.fixture
def supervisor(server):
    stop = threading.Event()
    made = {}

    def make_worker(device):
        if device["name"] == "unrunnable":
            raise ValueError("cannot run it")
        made[device["id"]] = FakeProvider()
        return DeviceWorker(
            device["id"],
            made[device["id"]],
            make_api(server),
            RetryPolicy(3, 0.0),
            sleep=lambda s: None,
        )

    sup = Supervisor(make_api(server), make_worker, stop, interval=0.01)
    sup.made = made
    yield sup, stop
    stop.set()
    sup.stop_all()
    sup.join(timeout=10)


def device(i, name=None):
    return {"id": i, "name": name or f"d{i}", "phone_number": "+639170000000"}


def test_it_starts_a_loop_per_assigned_device_and_states_what_it_is(server, supervisor):
    sup, _ = supervisor
    server.devices = [device(1), device(2)]
    assert sorted(sup.sync()) == [1, 2] and sup.sync() == []
    assert "providers" not in server.sessions[0]
    assert server.sessions[0]["instance_id"] == sup.instance_id
    assert {s["instance_id"] for s in server.sessions} == {
        sup.instance_id
    }  # heartbeats, not restarts


def test_the_loops_really_work_the_queue(server, supervisor):
    sup, _ = supervisor
    server.devices = [device(1)]
    server.queue.append(message())
    sup.sync()
    assert wait_for(lambda: server.results == [(1, "sent", None)])


def test_a_device_taken_away_is_stopped_and_not_restarted(server, supervisor):
    sup, _ = supervisor
    server.devices = [device(1)]
    sup.sync()
    server.devices = []
    sup.sync()
    assert wait_for(lambda: sup.running() == 0) and sup.made[1].closed
    assert sup.sync() == []


def test_a_device_it_cannot_run_is_skipped_once(server, supervisor):
    sup, _ = supervisor
    server.devices = [device(1), device(2, "unrunnable")]
    assert sup.sync() == [1] and sup.sync() == []


def test_a_new_instance_each_time_the_worker_starts(server, supervisor):
    first, _ = supervisor
    other = Supervisor(make_api(server), lambda d: None, threading.Event(), 0.01)
    assert first.instance_id != other.instance_id


def test_it_beats_only_while_the_api_answers(server, supervisor):
    sup, stop = supervisor
    beats = []
    server.fail["/worker/session"] = [503, 503]
    calls = []
    original = sup.sync

    def counted():
        calls.append(1)
        if len(calls) >= 3:
            stop.set()
        return original()

    sup.sync = counted
    sup.run(lambda: beats.append(1))
    assert len(calls) == 3 and len(beats) == 1


def test_the_providers_get_the_id_of_the_message_they_send(server, api, sleeps):
    server.queue += [message(11), message(12)]
    provider = FakeProvider()
    send_one(api, provider, 3, POLICY, sleeps.append)
    send_one(api, provider, 3, POLICY, sleeps.append)
    assert provider.sent_ids == [11, 12]


def test_a_retry_sends_the_same_message_id_again(server, api, sleeps):
    server.queue.append(message(21))
    provider = FakeProvider()
    provider.send_errors.append(ProviderError("busy"))
    ids = []
    provider.on_send = lambda phone, content: None
    original = provider.send

    def spy(phone, content, message_id=None):
        ids.append(message_id)
        return original(phone, content, message_id)

    provider.send = spy
    send_one(api, provider, 3, POLICY, sleeps.append)
    assert ids == [21, 21]
