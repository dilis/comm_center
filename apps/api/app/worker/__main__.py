"""The GSM worker process: ``python -m app.worker --provider fake``.

A process of its own (never a thread of the API): it holds the serial ports. It runs one loop per
registered device, each in its own thread, and keeps watching for devices registered later. It
stops cleanly on SIGINT or SIGTERM.
"""

import argparse
import logging
import signal
import threading
from pathlib import Path

from app.config import settings
from app.db import SessionLocal
from app.devices import ensure_fake_device
from app.worker.fake import FakeProvider
from app.worker.outbound import RetryPolicy
from app.worker.runner import DeviceWorker
from app.worker.supervisor import Supervisor

log = logging.getLogger("app.worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.worker")
    parser.add_argument(
        "--provider",
        required=True,
        choices=["fake"],  # the real modem provider arrives with the hardware
        help="fake: no modem; sends are only logged (and marked sent)",
    )
    parser.add_argument(
        "--fake-inbox", type=Path, help="fake provider: JSON-lines file of inbound SMS"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    log.warning("FAKE provider: messages are marked sent but NOT transmitted by any modem")
    with SessionLocal() as db:
        created = ensure_fake_device(db)
    if created:
        log.info("no device was registered, so a fake one was added (%s)", created.name)

    heartbeat_file = Path(settings.worker_heartbeat_file)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    policy = RetryPolicy(settings.worker_max_attempts, settings.worker_backoff_base_seconds)

    def make_worker(device_id: int) -> DeviceWorker:
        return DeviceWorker(
            device_id,
            FakeProvider(inbox_file=args.fake_inbox),
            SessionLocal,
            policy,
            sleep=lambda seconds: stop.wait(seconds),
            heartbeat=heartbeat_file.touch,
        )

    Supervisor(SessionLocal, make_worker, stop, settings.worker_poll_interval_seconds).run(
        heartbeat_file.touch
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
