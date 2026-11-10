"""One loop per device: poll inbound, send a bounded batch of queued messages, repeat."""

import logging
import threading
import time
from collections.abc import Callable

from comm_center_worker.client import ApiClient, ApiUnavailable
from comm_center_worker.inbound import process_inbound
from comm_center_worker.outbound import RetryPolicy, report_device_error, send_one
from comm_center_worker.provider import ChannelProvider, ProviderError

log = logging.getLogger(__name__)


class DeviceWorker:
    def __init__(
        self,
        device_id: int,
        provider: ChannelProvider,
        api: ApiClient,
        policy: RetryPolicy,
        *,
        sleep: Callable[[float], None] = time.sleep,
        heartbeat: Callable[[], None] = lambda: None,
        max_sends_per_cycle: int = 5,
        send_interval: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.device_id = device_id
        self.provider = provider
        self.api = api
        self.policy = policy
        self.sleep = sleep
        self.heartbeat = heartbeat
        self.max_sends_per_cycle = max_sends_per_cycle
        # Carriers may throttle bulk sending, so keep at least this many seconds between sends.
        self.send_interval = max(0.0, send_interval)
        self._clock = clock
        self._next_send_at = 0.0
        self._status: str | None = None

    def _set_status(self, status: str) -> None:
        if status == self._status:
            return
        self.api.device_status(self.device_id, status)
        self._status = status

    def run_once(self) -> int:
        """One cycle. Returns how much work was done (messages received plus sent). Raises
        ``ApiUnavailable`` when the API cannot be reached."""
        try:
            done = process_inbound(self.api, self.provider, self.device_id)
        except ProviderError as exc:
            log.error("device %s: unavailable: %s", self.device_id, exc)
            report_device_error(self.api, self.device_id, str(exc))
            self._status = "error"
            return 0
        self._set_status("online")
        for _ in range(self.max_sends_per_cycle):
            # Wait before claiming, not after: a message stays queued (and unleased) while we wait.
            if self._clock() < self._next_send_at:
                break
            if not send_one(self.api, self.provider, self.device_id, self.policy, self.sleep):
                break
            done += 1
            if self.send_interval:
                self._next_send_at = self._clock() + self.send_interval
        return done

    def _idle_wait(self, interval: float) -> float:
        """How long to rest when there was no work: the poll interval, but no longer than it takes
        for the next send to become due, so the spacing is not stretched by the poll interval."""
        until_due = self._next_send_at - self._clock()
        return min(interval, until_due) if until_due > 0 else interval

    def run_forever(self, stop: threading.Event, interval: float) -> None:
        try:
            while not stop.is_set():
                try:
                    worked = self.run_once()
                except ApiUnavailable as exc:
                    log.warning("device %s: %s; trying again", self.device_id, exc)
                    worked = 0
                except Exception:
                    log.exception("device %s: cycle failed", self.device_id)
                    worked = 0
                self.heartbeat()
                if not worked:
                    stop.wait(self._idle_wait(interval))
        finally:
            try:
                self.api.device_status(self.device_id, "offline")
            except Exception:
                log.exception("device %s: could not record offline status", self.device_id)
            self.provider.close()
