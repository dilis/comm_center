"""The channel boundary: everything the worker needs from a modem (or any other channel)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ProviderError(Exception):
    """The channel failed in a way that may pass (modem busy, no signal): worth a retry."""


class PermanentSendError(ProviderError):
    """The channel rejected this message for good (e.g. an invalid number): never retried."""


@dataclass(frozen=True)
class InboundSms:
    ref: str  # the provider's handle for acknowledging (e.g. a SIM storage index)
    sender: str  # as the network reports it; may not be a phone number
    content: str
    received_at: datetime


class ChannelProvider(Protocol):
    def send(self, phone_number: str, content: str, message_id: int | None = None) -> None:
        """Send one message to an E.164 number. Raises ``ProviderError`` on failure.

        ``message_id`` is our id for the message. A provider that can use it as an idempotency key,
        or to match delivery reports later, should (the same id is passed again on a retry)."""

    def poll_inbound(self) -> list[InboundSms]:
        """Messages received and not yet acknowledged. Raises ``ProviderError`` if unreachable."""

    def acknowledge(self, sms: InboundSms) -> None:
        """Forget ``sms`` (delete it from the modem). Called only after it is safely stored."""

    def close(self) -> None: ...
