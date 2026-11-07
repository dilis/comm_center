"""One loop per device: poll inbound, send a bounded batch of queued messages, repeat."""

import logging
import threading
import time
from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.models import GsmDevice
from app.worker.inbound import process_inbound
from app.worker.outbound import RetryPolicy, recover_interrupted, send_one
from app.worker.provider import ChannelProvider, ProviderError

log = logging.getLogger(__name__)


class DeviceWorker:
    def __init__(
        self,
        device_id: int,
        provider: ChannelProvider,
        session_factory: sessionmaker,
        policy: RetryPolicy,
        *,
        sleep: Callable[[float], None] = time.sleep,
        heartbeat: Callable[[], None] = lambda: None,
        max_sends_per_cycle: int = 20,
    ) -> None:
        self.device_id = device_id
        self.provider = provider
        self.session_factory = session_factory
        self.policy = policy
        self.sleep = sleep
        self.heartbeat = heartbeat
        self.max_sends_per_cycle = max_sends_per_cycle
        self._status: str | None = None

    def start(self) -> None:
        with self.session_factory() as db:
            failed = recover_interrupted(db, self.device_id)
        if failed:
            log.warning(
                "device %s: %s message(s) left 'sending' were marked failed", self.device_id, failed
            )

    def _device(self) -> GsmDevice | None:
        with self.session_factory() as db:
            return db.scalars(select(GsmDevice).where(GsmDevice.id == self.device_id)).one_or_none()

    def _set_status(self, status: str) -> None:
        if status == self._status:
            return
        with self.session_factory() as db:
            db.execute(
                update(GsmDevice).where(GsmDevice.id == self.device_id).values(status=status)
            )
            db.commit()
        self._status = status

    def run_once(self) -> int:
        """One cycle. Returns how much work was done (messages received plus sent)."""
        device = self._device()
        if device is None:
            raise LookupError(f"device {self.device_id} no longer exists")
        try:
            done = process_inbound(self.session_factory, self.provider, device)
        except ProviderError as exc:
            log.error("device %s: modem unavailable: %s", self.device_id, exc)
            self._set_status("error")
            return 0
        self._set_status("online")
        for _ in range(self.max_sends_per_cycle):
            if not send_one(
                self.session_factory, self.provider, self.device_id, self.policy, self.sleep
            ):
                break
            done += 1
        return done

    def run_forever(self, stop: threading.Event, interval: float) -> None:
        try:
            self.start()
            while not stop.is_set():
                try:
                    worked = self.run_once()
                except LookupError:
                    log.error("device %s was removed; stopping its loop", self.device_id)
                    return
                except Exception:
                    log.exception("device %s: cycle failed", self.device_id)
                    worked = 0
                self.heartbeat()
                if not worked:
                    stop.wait(interval)
        finally:
            try:
                self._set_status("offline")
            except Exception:
                log.exception("device %s: could not record offline status", self.device_id)
            self.provider.close()
