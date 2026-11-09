import json

import pytest

from app.worker.fake import FakeProvider
from app.worker.outbound import RetryPolicy
from app.worker.provider import PermanentSendError, ProviderError


def test_backoff_doubles_each_attempt():
    policy = RetryPolicy(max_attempts=4, backoff_base=2.0)
    assert [policy.delay(n) for n in (1, 2, 3)] == [2.0, 4.0, 8.0]


def test_permanent_errors_are_provider_errors():
    assert issubclass(PermanentSendError, ProviderError)


def test_fake_provider_records_sends_and_raises_scripted_errors():
    fake = FakeProvider()
    fake.send("+639171234567", "hi")
    assert fake.sent == [("+639171234567", "hi")]
    fake.send_errors.append(ProviderError("modem busy"))
    with pytest.raises(ProviderError, match="modem busy"):
        fake.send("+639171234567", "again")
    assert len(fake.sent) == 1  # a failed send is not recorded


def test_fake_provider_inbox_file_is_read_incrementally(tmp_path):
    inbox = tmp_path / "inbox.jsonl"
    fake = FakeProvider(inbox_file=inbox)
    assert fake.poll_inbound() == []  # no file yet
    inbox.write_text(json.dumps({"from": "+639171234567", "text": "one"}) + "\n")
    first = fake.poll_inbound()
    assert [(s.sender, s.content) for s in first] == [("+639171234567", "one")]
    assert len(fake.poll_inbound()) == 1  # like a modem: re-delivered until acknowledged
    fake.acknowledge(first[0])
    assert fake.poll_inbound() == []
    with inbox.open("a") as f:
        f.write(json.dumps({"from": "0917 123 4567", "text": "two"}) + "\n")
        f.write("not json\n")  # ignored, not fatal
    assert [s.content for s in fake.poll_inbound()] == ["two"]


def test_the_worker_needs_a_name_and_secret_to_start(capsys, monkeypatch):
    from app.config import settings
    from app.worker.__main__ import main

    monkeypatch.setattr(settings, "worker_name", "")
    monkeypatch.setattr(settings, "worker_secret", "")
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2
    assert "WORKER_NAME" in capsys.readouterr().err


def test_fake_provider_takes_time_to_send_like_a_modem():
    slept = []
    fake = FakeProvider(send_delay=2.0, send_jitter=1.0, sleep=slept.append)
    for _ in range(50):
        fake.send("+639171234567", "hi")
    assert len(slept) == 50 and all(2.0 <= s <= 3.0 for s in slept)
    assert len(set(slept)) > 1  # not the same every time
    assert len(fake.sent) == 50


def test_fake_provider_sleeps_before_it_records_the_send():
    order = []
    fake = FakeProvider(send_delay=1.0, sleep=lambda s: order.append(("slept", len(fake.sent))))
    fake.send("+639171234567", "hi")
    assert order == [("slept", 0)]  # the sleep happened while the message was not yet "sent"


def test_a_failed_send_does_not_wait():
    slept = []
    fake = FakeProvider(send_delay=2.0, sleep=slept.append)
    fake.send_errors.append(ProviderError("busy"))
    with pytest.raises(ProviderError):
        fake.send("+639171234567", "hi")
    assert slept == []


def test_by_default_the_fake_provider_is_instant_so_tests_stay_fast():
    slept = []
    FakeProvider(sleep=slept.append).send("+639171234567", "hi")
    assert slept == []


def test_fake_inbox_refs_are_unique_across_restarts(tmp_path):
    """The API stores a ref once per device, so a restarted provider must not reuse `file-1`."""
    inbox = tmp_path / "inbox.jsonl"
    inbox.write_text(json.dumps({"from": "0917 123 4567", "text": "one"}) + "\n")
    first = FakeProvider(inbox_file=inbox).poll_inbound()
    second = FakeProvider(inbox_file=inbox).poll_inbound()  # a restart reads the file again
    assert first[0].ref != second[0].ref
    one = FakeProvider(inbox_file=inbox)
    with inbox.open("a") as f:
        f.write(json.dumps({"from": "0917 123 4567", "text": "two"}) + "\n")
    assert len({s.ref for s in one.poll_inbound()}) == 2  # and within one run
