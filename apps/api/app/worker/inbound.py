"""Inbound: hand what the device received to the API, forgetting it on the device only after the
API has stored it."""

import logging

from app.worker.client import ApiClient, ApiUnavailable
from app.worker.provider import ChannelProvider

log = logging.getLogger(__name__)


def process_inbound(api: ApiClient, provider: ChannelProvider, device_id: int) -> int:
    """Poll the device and give each message to the API, acknowledging only once the API has
    answered (so a crash re-delivers rather than loses). A message the API cannot take now is left
    on the device. Returns how many messages the API stored."""
    stored = 0
    for sms in provider.poll_inbound():
        try:
            result = api.inbound(device_id, sms)
        except ApiUnavailable:
            raise  # the API is down: stop and try the whole cycle later
        except Exception:
            log.exception("could not store SMS %s; leaving it on the device", sms.ref)
            continue
        provider.acknowledge(
            sms
        )  # also forgets unusable and repeated ones, or they would come back
        stored += result.stored
    return stored
