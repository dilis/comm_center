"""The worker process: ``python -m comm_center_worker``.

A process of its own that holds a device (a serial port, a phone). It signs in to the API as that
device's agent, learns from it which device it serves and runs a loop for it. Which kind of device
that is (``WORKER_PROVIDER``) and how to reach it is this process's own business: the API does not
know. It never touches the database. It stops cleanly on SIGINT or SIGTERM.
"""

import argparse
import logging
import signal
import threading
from pathlib import Path

import httpx

from comm_center_worker.android import from_config
from comm_center_worker.client import ApiClient
from comm_center_worker.config import settings
from comm_center_worker.fake import FakeProvider
from comm_center_worker.logging_config import configure_logging
from comm_center_worker.outbound import RetryPolicy
from comm_center_worker.provider import ChannelProvider
from comm_center_worker.runner import DeviceWorker
from comm_center_worker.supervisor import Supervisor

log = logging.getLogger("comm_center_worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="comm_center_worker")
    parser.add_argument(
        "--fake-inbox", type=Path, help="fake provider: JSON-lines file of inbound SMS"
    )
    args = parser.parse_args(argv)
    if not (settings.worker_name and settings.worker_secret):
        parser.error("WORKER_NAME and WORKER_SECRET are required (see `register-device`)")
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
        if settings.worker_provider == "fake":
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
        if settings.worker_provider == "android":
            return from_config(
                settings.worker_android_base_url,
                settings.worker_android_username,
                settings.worker_android_password,
                timeout=settings.worker_android_timeout_seconds,
            )
        raise ValueError(f"this worker cannot run provider {settings.worker_provider!r}")

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
        Supervisor(api, make_worker, stop, settings.worker_poll_interval_seconds).run(
            heartbeat_file.touch
        )
    finally:
        api.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
