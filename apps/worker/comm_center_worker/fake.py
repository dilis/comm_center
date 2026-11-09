"""A scripted ``ChannelProvider`` for tests and for trying the worker without a modem."""

import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from comm_center_worker.provider import InboundSms, ProviderError

log = logging.getLogger(__name__)


class FakeProvider:
    """Records sends. Tests script failures through ``send_errors`` / ``poll_errors`` (each entry
    is raised once, in order) and feed messages through ``inbound``. With ``inbox_file``, new JSON
    lines ``{"from": "...", "text": "..."}`` appended to that file arrive as inbound messages."""

    def __init__(
        self,
        inbox_file: Path | None = None,
        *,
        send_delay: float = 0.0,
        send_jitter: float = 0.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        # A real modem needs a few seconds per SMS: each send waits ``send_delay`` plus up to
        # ``send_jitter`` seconds (0 by default, so tests are instant). ``sleep`` is injectable so
        # the worker can make the wait interruptible on shutdown.
        self.send_delay = send_delay
        self.send_jitter = send_jitter
        self._sleep = sleep
        self.sent: list[tuple[str, str]] = []
        self.sent_ids: list[int | None] = []
        self.inbound: list[InboundSms] = []
        self.acknowledged: list[InboundSms] = []
        self.send_errors: list[Exception] = []
        self.poll_errors: list[Exception] = []
        self.on_send: Callable[[str, str], None] | None = None
        self.on_acknowledge: Callable[[InboundSms], None] | None = None
        self.closed = False
        self._inbox_file = inbox_file
        self._inbox_offset = 0
        self._inbox_count = 0
        # Refs identify a message for good (the API stores each once), so they must differ between
        # runs: a restarted process would otherwise reuse `file-1`.
        self._run_id = uuid.uuid4().hex[:8]

    def send(self, phone_number: str, content: str, message_id: int | None = None) -> None:
        if self.send_errors:
            raise self.send_errors.pop(0)
        if self.on_send:
            self.on_send(phone_number, content)
        if self.send_delay > 0 or self.send_jitter > 0:
            self._sleep(self.send_delay + random.uniform(0, self.send_jitter))
        log.info("fake send to %s: %r", phone_number, content)
        self.sent.append((phone_number, content))
        self.sent_ids.append(message_id)

    def poll_inbound(self) -> list[InboundSms]:
        if self.poll_errors:
            raise self.poll_errors.pop(0)
        self._read_inbox_file()
        acked = {s.ref for s in self.acknowledged}
        return [s for s in self.inbound if s.ref not in acked]

    def acknowledge(self, sms: InboundSms) -> None:
        if self.on_acknowledge:
            self.on_acknowledge(sms)
        self.acknowledged.append(sms)

    def close(self) -> None:
        self.closed = True

    def _read_inbox_file(self) -> None:
        if self._inbox_file is None or not self._inbox_file.exists():
            return
        with self._inbox_file.open("rb") as f:
            f.seek(self._inbox_offset)
            data = f.read()
        complete = data[: data.rfind(b"\n") + 1]  # a half-written last line waits for next poll
        self._inbox_offset += len(complete)
        for line in complete.decode("utf-8", "replace").splitlines():
            try:
                item = json.loads(line)
                sender, text = str(item["from"]), str(item["text"])
            except (ValueError, KeyError, TypeError):
                log.warning("ignoring malformed inbox line: %r", line)
                continue
            self._inbox_count += 1
            self.inbound.append(
                InboundSms(
                    ref=f"file-{self._run_id}-{self._inbox_count}",
                    sender=sender,
                    content=text,
                    received_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )


__all__ = ["FakeProvider", "ProviderError"]
