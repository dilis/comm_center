"""Keeps one loop running per registered device, picking up devices registered later."""

import logging
import threading
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import GsmDevice
from app.worker.runner import DeviceWorker

log = logging.getLogger(__name__)


class Supervisor:
    def __init__(
        self,
        session_factory: sessionmaker,
        make_worker: Callable[[int], DeviceWorker],
        stop: threading.Event,
        interval: float,
    ) -> None:
        self.session_factory = session_factory
        self.make_worker = make_worker
        self.stop = stop
        self.interval = interval
        self._threads: dict[int, threading.Thread] = {}

    def running(self) -> int:
        return sum(t.is_alive() for t in self._threads.values())

    def sync(self) -> list[int]:
        """Start a loop for every registered device that has none. Returns the new device ids.
        A loop whose device was removed ends by itself and is simply forgotten here."""
        with self.session_factory() as db:
            ids = list(db.scalars(select(GsmDevice.id).order_by(GsmDevice.id)))
        self._threads = {i: t for i, t in self._threads.items() if t.is_alive()}
        started = []
        for device_id in ids:
            if device_id in self._threads:
                continue
            worker = self.make_worker(device_id)
            thread = threading.Thread(
                target=worker.run_forever,
                args=(self.stop, self.interval),
                name=f"device-{device_id}",
            )
            thread.start()
            self._threads[device_id] = thread
            started.append(device_id)
            log.info("started the loop for device %s", device_id)
        return started

    def join(self, timeout: float | None = None) -> None:
        for thread in list(self._threads.values()):
            thread.join(timeout)

    def run(self, heartbeat: Callable[[], None]) -> None:
        """Sync and beat until ``stop`` is set (a heartbeat even with no devices, so the process
        reads as healthy while it waits for one), then wait for the loops to finish."""
        try:
            while not self.stop.is_set():
                try:
                    self.sync()
                except Exception:
                    log.exception("could not look for new devices")
                heartbeat()
                self.stop.wait(self.interval)
        finally:
            self.join()
