"""The worker process: ``python -m app.worker``.

A process of its own that holds the devices (serial ports, phones). It signs in to the API as a
worker account, learns from it which devices are assigned to it and runs one loop per device, each
in its own thread. It never touches the database. It stops cleanly on SIGINT or SIGTERM.
"""

import argparse
import logging
import signal
import threading
from pathlib import Path

import httpx

from app.config import settings
from app.logging_config import configure_logging
from app.worker.client import ApiClient
from app.worker.fake import FakeProvider
from app.worker.outbound import RetryPolicy
from app.worker.provider import ChannelProvider
from app.worker.runner import DeviceWorker
from app.worker.supervisor import Supervisor

log = logging.getLogger("app.worker")

# Provider types this worker can run. The API decides which device uses which.
SUPPORTED_PROVIDERS = ["fake"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.worker")
    parser.add_argument(
        "--fake-inbox", type=Path, help="fake provider: JSON-lines file of inbound SMS"
    )
    args = parser.parse_args(argv)
    if not (settings.worker_name and settings.worker_secret):
        parser.error("WORKER_NAME and WORKER_SECRET are required (see `create-worker`)")
    configure_logging(settings.log_level)

    heartbeat_file = Path(settings.worker_heartbeat_file)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    policy = RetryPolicy(settings.worker_max_attempts, settings.worker_backoff_base_seconds)

    def new_api() -> ApiClient:
        # Each loop gets its own client (an httpx client is not meant to be shared across threads).
        http = httpx.Client(base_url=settings.worker_api_url, timeout=30)
        return ApiClient(http, settings.worker_name, settings.worker_secret)

    def make_provider(device: dict) -> ChannelProvider:
        if device["provider"] == "fake":
            log.warning(
                "device %s uses the FAKE provider: messages are marked sent but NOT transmitted",
                device["name"],
            )
            return FakeProvider(
                inbox_file=args.fake_inbox,
                send_delay=settings.worker_fake_send_delay_seconds,
                send_jitter=settings.worker_fake_send_jitter_seconds,
                sleep=lambda seconds: stop.wait(seconds),  # a shutdown interrupts a pending send
            )
        raise ValueError(f"this worker cannot run provider {device['provider']!r}")

    def make_worker(device: dict) -> DeviceWorker:
        return DeviceWorker(
            device["id"],
            make_provider(device),
            new_api(),
            policy,
            sleep=lambda seconds: stop.wait(seconds),
            heartbeat=heartbeat_file.touch,
        )

    api = new_api()
    try:
        Supervisor(
            api, make_worker, SUPPORTED_PROVIDERS, stop, settings.worker_poll_interval_seconds
        ).run(heartbeat_file.touch)
    finally:
        api.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
