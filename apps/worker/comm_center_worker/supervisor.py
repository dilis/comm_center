"""Keeps a loop running for the device the API says this worker serves, picking up changes."""

import logging
import threading
import uuid
from collections.abc import Callable

from comm_center_worker.client import ApiClient
from comm_center_worker.protocol import PROTOCOL_VERSION, WORKER_VERSION
from comm_center_worker.runner import DeviceWorker

log = logging.getLogger(__name__)


class Supervisor:
    def __init__(
        self,
        api: ApiClient,
        make_worker: Callable[[dict], DeviceWorker],
        stop: threading.Event,
        interval: float,
    ) -> None:
        self.api = api
        self.make_worker = make_worker
        self.stop = stop
        self.interval = interval
        # Told to the API with every session: the same one is a heartbeat, a new one a restart.
        self.instance_id = uuid.uuid4().hex
        self._loops: dict[int, tuple[threading.Thread, threading.Event]] = {}
        self._unusable: set[int] = set()

    def running(self) -> int:
        return sum(t.is_alive() for t, _ in self._loops.values())

    def sync(self) -> list[int]:
        """Ask the API which devices are ours (this is also the heartbeat). Start a loop for each
        new one and stop the loop of any device no longer assigned. Returns the new device ids."""
        session = self.api.session(WORKER_VERSION, self.instance_id, PROTOCOL_VERSION)
        devices = {d["id"]: d for d in session["devices"]}
        for device_id, (_, stop_loop) in list(self._loops.items()):
            if device_id not in devices:
                log.info("device %s is no longer assigned to this worker; stopping it", device_id)
                stop_loop.set()
        self._loops = {i: lp for i, lp in self._loops.items() if lp[0].is_alive()}
        started = []
        for device_id, device in devices.items():
            if device_id in self._loops or device_id in self._unusable:
                continue
            try:
                worker = self.make_worker(device)
            except Exception:
                log.exception("device %s (%s): cannot run it here", device_id, device.get("name"))
                self._unusable.add(device_id)  # logged once, not on every sync
                continue
            stop_loop = threading.Event()
            thread = threading.Thread(
                target=worker.run_forever,
                args=(_either(self.stop, stop_loop), self.interval),
                name=f"device-{device_id}",
            )
            thread.start()
            self._loops[device_id] = (thread, stop_loop)
            started.append(device_id)
            log.info("started the loop for device %s", device_id)
        return started

    def stop_all(self) -> None:
        for _, stop_loop in self._loops.values():
            stop_loop.set()

    def join(self, timeout: float | None = None) -> None:
        for thread, _ in list(self._loops.values()):
            thread.join(timeout)

    def run(self, heartbeat: Callable[[], None]) -> None:
        """Sync and beat until ``stop`` is set, then wait for the loops to finish. The heartbeat is
        touched only when the API answered, so a worker that cannot reach it reads as unhealthy."""
        try:
            while not self.stop.is_set():
                try:
                    self.sync()
                except Exception as exc:  # noqa: BLE001 - any failure: keep running, stay unhealthy
                    log.error("could not reach the API for this worker's devices: %s", exc)
                else:
                    heartbeat()
                self.stop.wait(self.interval)
        finally:
            self.stop_all()
            self.join()


class _either(threading.Event):
    """An event that is set when either of two events is: a loop stops on shutdown or when its
    device is taken away."""

    def __init__(self, first: threading.Event, second: threading.Event) -> None:
        super().__init__()
        self._first, self._second = first, second

    def is_set(self) -> bool:
        return self._first.is_set() or self._second.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        # Short slices, so either event ends the wait promptly.
        remaining = timeout
        while True:
            if self.is_set():
                return True
            step = 0.1 if remaining is None else min(0.1, remaining)
            if remaining is not None and remaining <= 0:
                return False
            self._first.wait(step)
            if remaining is not None:
                remaining -= step
