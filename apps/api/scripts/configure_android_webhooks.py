"""Configure this project's webhooks on an Android SMS Gateway Local Server.

    uv run python -m scripts.configure_android_webhooks all \
        http://192.168.1.50:8080 --username sms \
        --webhook-url https://sms.example.com/api/devices/1/webhook
    uv run python -m scripts.configure_android_webhooks event \
        http://192.168.1.50:8080 --username sms \
        --webhook-url https://sms.example.com/api/devices/1/webhook \
        --event sms:received
    uv run python -m scripts.configure_android_webhooks signing-key \
        http://192.168.1.50:8080 --username sms \
        --webhook-url https://sms.example.com/api/devices/1/webhook
    uv run python -m scripts.configure_android_webhooks delete \
        http://192.168.1.50:8080 cc-received --username sms

Each webhook is registered under a fixed ID (cc-received, cc-delivered, cc-failed, cc-sent), so
registering again replaces it and `delete` takes that ID.

The gateway password is read from ANDROID_SMS_GATEWAY_PASSWORD or prompted for securely.
"""

import argparse
import getpass
import os
import re
import sys
from urllib.parse import quote, urlsplit

import httpx

from app import webhooks

WEBHOOK_EVENTS = ("sms:received", "sms:delivered", "sms:failed")
OPTIONAL_EVENTS = ("sms:sent",)
ID_PREFIX = "cc-"


def webhook_id_for(event: str) -> str:
    """The fixed gateway ID of this project's webhook for an event, e.g. cc-received."""
    return ID_PREFIX + event.split(":", 1)[1]


# Registered by hand under these IDs earlier; they can be deleted but are never registered.
LEGACY_WEBHOOK_IDS = ("cc-rdelivered", "cc-rfailed")
WEBHOOK_IDS = (
    *(webhook_id_for(event) for event in (*WEBHOOK_EVENTS, *OPTIONAL_EVENTS)),
    *LEGACY_WEBHOOK_IDS,
)


class GatewayError(Exception):
    """The gateway returned an unexpected response."""


def device_id_from_url(webhook_url: str) -> int:
    parsed = urlsplit(webhook_url)
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("the webhook URL must be an absolute URL without embedded credentials")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("the webhook URL must start with http:// or https://")
    match = re.search(r"(?:^|/)devices/([1-9][0-9]*)/webhook/?$", parsed.path)
    if match is None:
        raise ValueError("the webhook URL path must end with /devices/<id>/webhook")
    return int(match.group(1))


def _existing_webhooks(client: httpx.Client) -> list[dict[str, object]]:
    response = client.get("/webhooks")
    response.raise_for_status()
    try:
        result = response.json()
    except ValueError as exc:
        raise GatewayError("the gateway returned invalid JSON for its webhook list") from exc
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        raise GatewayError("the gateway returned an invalid webhook list")
    return result


def configure_webhooks(
    client: httpx.Client, webhook_url: str, events: tuple[str, ...]
) -> dict[str, bool]:
    device_id_from_url(webhook_url)
    existing = _existing_webhooks(client)
    configured: dict[str, bool] = {}
    for event in events:
        webhook_id = webhook_id_for(event)
        if any(
            item.get("id") == webhook_id
            and item.get("url") == webhook_url
            and item.get("event") == event
            for item in existing
        ):
            configured[event] = False
            continue
        # The gateway replaces a webhook that already has this ID.
        response = client.post(
            "/webhooks", json={"id": webhook_id, "url": webhook_url, "event": event}
        )
        response.raise_for_status()
        configured[event] = True
    return configured


def configure_signing_key(client: httpx.Client, webhook_url: str) -> int:
    device_id = device_id_from_url(webhook_url)
    response = client.patch(
        "/settings",
        json={"webhooks": {"signing_key": webhooks.device_key(device_id)}},
    )
    response.raise_for_status()
    return device_id


def delete_webhook(client: httpx.Client, webhook_id: str) -> None:
    """Delete one webhook by its ID (see ``WEBHOOK_IDS``)."""
    response = client.delete(f"/webhooks/{quote(webhook_id, safe='')}")
    response.raise_for_status()


def _add_connection_options(parser: argparse.ArgumentParser, *, webhook_url: bool = True) -> None:
    parser.add_argument("gateway_url", metavar="GATEWAY_URL", help="Android Local Server base URL")
    parser.add_argument(
        "--username",
        default=os.environ.get("ANDROID_SMS_GATEWAY_USERNAME"),
        help="Local Server username (or ANDROID_SMS_GATEWAY_USERNAME)",
    )
    if webhook_url:
        parser.add_argument("--webhook-url", required=True, help="Comm Center device webhook URL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.configure_android_webhooks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    all_parser = subparsers.add_parser("all", help="register the three Comm Center webhook events")
    _add_connection_options(all_parser)

    event_parser = subparsers.add_parser("event", help="register one Comm Center webhook event")
    _add_connection_options(event_parser)
    event_parser.add_argument(
        "--event", required=True, choices=(*WEBHOOK_EVENTS, *OPTIONAL_EVENTS)
    )

    key_parser = subparsers.add_parser("signing-key", help="set this device's signing key")
    _add_connection_options(key_parser)

    delete_parser = subparsers.add_parser("delete", help="delete one webhook by its ID")
    _add_connection_options(delete_parser, webhook_url=False)
    delete_parser.add_argument(
        "webhook_id", metavar="WEBHOOK_ID", choices=WEBHOOK_IDS, help=f"one of {', '.join(WEBHOOK_IDS)}"
    )

    args = parser.parse_args(argv)
    if not args.username:
        parser.error("provide --username or set ANDROID_SMS_GATEWAY_USERNAME")
    try:
        if args.command != "delete":
            device_id_from_url(args.webhook_url)
        gateway_url = urlsplit(args.gateway_url)
        if (
            gateway_url.scheme not in ("http", "https")
            or not gateway_url.hostname
            or gateway_url.path not in ("", "/")
            or gateway_url.username
            or gateway_url.password
            or gateway_url.query
            or gateway_url.fragment
        ):
            raise ValueError(
                "gateway URL must be an HTTP(S) base URL without embedded credentials or a path"
            )
    except ValueError as exc:
        print(
            f"error: {exc}",
            file=sys.stderr,
        )
        return 1
    password = os.environ.get("ANDROID_SMS_GATEWAY_PASSWORD") or getpass.getpass(
        "Android SMS Gateway password: "
    )

    try:
        with httpx.Client(
            base_url=args.gateway_url.rstrip("/"), auth=(args.username, password), timeout=15.0
        ) as client:
            if args.command == "all":
                configured = configure_webhooks(client, args.webhook_url, WEBHOOK_EVENTS)
                for event, added in configured.items():
                    print(f"{'registered' if added else 'already registered'}: {event}")
            elif args.command == "event":
                configured = configure_webhooks(client, args.webhook_url, (args.event,))
                state = "registered" if configured[args.event] else "already registered"
                print(f"{state}: {args.event}")
            elif args.command == "signing-key":
                device_id = configure_signing_key(client, args.webhook_url)
                print(f"configured signing key for device {device_id}")
            else:
                delete_webhook(client, args.webhook_id)
                print(f"deleted webhook {args.webhook_id}")
    except (GatewayError, ValueError, httpx.HTTPError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
