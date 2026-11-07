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


def test_only_the_fake_provider_exists_until_hardware_arrives(capsys):
    from app.worker.__main__ import main

    with pytest.raises(SystemExit) as exit_info:
        main(["--provider", "serial"])
    assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
