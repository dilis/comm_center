"""Outbound: claim a queued message from the API, send it through the provider, report the result."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.worker.client import ApiClient, ApiConflict, ApiUnavailable
from app.worker.provider import ChannelProvider, PermanentSendError, ProviderError

log = logging.getLogger(__name__)
REPORT_ATTEMPTS = 3  # tries to deliver a result to the API before giving up


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_base: float = 2.0  # seconds before the 2nd attempt; doubles each time

    def delay(self, attempt: int) -> float:
        """Wait after failed attempt number ``attempt`` (1-based)."""
        return self.backoff_base * 2 ** (attempt - 1)


def report_result(
    api: ApiClient,
    message_id: int,
    status: str,
    error: str | None,
    policy: RetryPolicy,
    sleep: Callable[[float], None],
) -> None:
    """Tell the API how the send ended. If it cannot be told, the message is failed by the API when
    its lease runs out (delivery unknown): never re-sent."""
    for attempt in range(1, REPORT_ATTEMPTS + 1):
        try:
            api.result(message_id, status, error)
            return
        except ApiConflict as exc:
            log.warning("message %s: the API no longer holds it for us (%s)", message_id, exc)
            return
        except ApiUnavailable as exc:
            if attempt == REPORT_ATTEMPTS:
                log.error(
                    "message %s: could not report %r (%s); the API will fail it when its lease "
                    "runs out",
                    message_id,
                    status,
                    exc,
                )
                return
            sleep(policy.delay(attempt))


def report_device_error(api: ApiClient, device_id: int, error: str) -> None:
    try:
        api.device_status(device_id, "error", error)
    except Exception:  # health reporting must never stop the worker
        log.exception("device %s: could not report the modem error", device_id)


def send_one(
    api: ApiClient,
    provider: ChannelProvider,
    device_id: int,
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
    wait_seconds: float = 0,
) -> bool:
    """Claim and send one message. Returns False when the queue is empty. Raises ``ApiUnavailable``
    if the API cannot be reached to claim."""
    claimed = api.claim(device_id, wait_seconds)
    if claimed is None:
        return False
    try:
        for attempt in range(1, policy.max_attempts + 1):
            try:
                provider.send(claimed.phone_number, claimed.content)
            except PermanentSendError as exc:
                report_result(api, claimed.id, "failed", str(exc), policy, sleep)
                log.warning("message %s rejected: %s", claimed.id, exc)
                return True
            except ProviderError as exc:
                if attempt == policy.max_attempts:
                    report_result(api, claimed.id, "failed", str(exc), policy, sleep)
                    report_device_error(api, device_id, str(exc))
                    log.warning("message %s failed after %s attempts: %s", claimed.id, attempt, exc)
                    return True
                log.info("message %s attempt %s failed (%s); retrying", claimed.id, attempt, exc)
                sleep(policy.delay(attempt))
                try:
                    api.extend(claimed.id)  # the retries take time: keep holding the message
                except (ApiUnavailable, ApiConflict) as exc2:
                    log.warning("message %s: could not extend the lease (%s)", claimed.id, exc2)
            else:
                report_result(api, claimed.id, "sent", None, policy, sleep)
                return True
    except Exception as exc:  # never leave a claimed message stuck in 'sending'
        log.exception("unexpected error sending message %s", claimed.id)
        report_result(api, claimed.id, "failed", f"unexpected error: {exc}", policy, sleep)
    return True
