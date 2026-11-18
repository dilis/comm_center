"""``python -m comm_center_notifier``: run the notifier until told to stop (SIGTERM or Ctrl-C)."""

import logging
import signal
import time
from pathlib import Path

from comm_center_notifier import sender
from comm_center_notifier.config import settings
from comm_center_notifier.db import connect
from comm_center_notifier.logging_config import configure_logging
from comm_center_notifier.runner import run_loop

log = logging.getLogger(__name__)


def main() -> int:
    configure_logging(settings.log_level)
    if not sender.push_enabled():
        log.warning("VAPID_PRIVATE_KEY and VAPID_SUBJECT are not both set: nothing will be sent")
    stopping = False

    def request_stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    beat = Path(settings.notifier_heartbeat_file)
    log.info("notifier started")
    run_loop(connect, heartbeat=beat.touch, sleep=time.sleep, stop=lambda: stopping)
    log.info("notifier stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
