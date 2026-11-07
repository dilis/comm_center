"""The GSM worker process: ``python -m app.worker --provider fake``.

A process of its own (never a thread of the API): it holds the serial ports. It runs one loop
per registered device, each in its own thread, until it receives SIGINT or SIGTERM.
"""

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import GsmDevice
from app.worker.fake import FakeProvider
from app.worker.outbound import RetryPolicy
from app.worker.runner import DeviceWorker

log = logging.getLogger("app.worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.worker")
    parser.add_argument(
        "--provider",
        required=True,
        choices=["fake"],  # the real modem provider arrives with the hardware
        help="fake: no modem; sends are only logged",
    )
    parser.add_argument(
        "--fake-inbox", type=Path, help="fake provider: JSON-lines file of inbound SMS"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    with SessionLocal() as db:
        devices = list(db.scalars(select(GsmDevice).order_by(GsmDevice.id)))
    if not devices:
        print("error: no devices registered; run `pnpm --filter @comm-center/api register-device`",
              file=sys.stderr)  # fmt: skip
        return 1

    heartbeat_file = Path(settings.worker_heartbeat_file)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    policy = RetryPolicy(settings.worker_max_attempts, settings.worker_backoff_base_seconds)

    threads = []
    for device in devices:
        worker = DeviceWorker(
            device.id,
            FakeProvider(inbox_file=args.fake_inbox),
            SessionLocal,
            policy,
            sleep=lambda seconds: stop.wait(seconds),
            heartbeat=heartbeat_file.touch,
        )
        log.info("starting %s on %s (fake provider)", device.name, device.serial_port)
        thread = threading.Thread(
            target=worker.run_forever,
            args=(stop, settings.worker_poll_interval_seconds),
            name=device.name,
        )
        thread.start()
        threads.append(thread)
    for thread in threads:
        while thread.is_alive():
            thread.join(timeout=1)  # short joins keep the main thread responsive to signals
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
