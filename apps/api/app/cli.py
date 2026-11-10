"""Admin commands: ``create-admin``, ``register-device``, ``ensure-device``, ``reset-device-secret``
and ``webhook-info`` (``python -m app.cli --help``)."""

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app import webhooks
from app.bootstrap import BootstrapError, create_admin
from app.db import SessionLocal
from app.devices import (
    AGENT_PREFIX,
    DeviceError,
    ensure_device,
    new_secret,
    register_device,
    set_device_secret,
)
from app.models import GsmDevice


def _show_secret(name: str, secret: str, created: str) -> None:
    print(
        f"{created} device '{name}'. The worker signs in as '{AGENT_PREFIX}{name}' with this secret,"
    )
    print("which is shown only now:")
    print(secret)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create the first administrator")
    admin.add_argument("--username", required=True)
    admin.add_argument("--name", help="display name (defaults to the username)")
    device = sub.add_parser(
        "register-device",
        help="register a GSM device and its inbound agent, and print the secret its worker uses",
    )
    device.add_argument("--name", required=True, help="short unique name; the agent is gsm-<name>")
    device.add_argument("--phone", required=True, help="the SIM's own number")
    ensure = sub.add_parser(
        "ensure-device",
        help="create a device (or reset its secret) with the secret from an environment variable",
    )
    ensure.add_argument("--name", required=True)
    ensure.add_argument("--phone", required=True, help="the SIM's own number (used if it is new)")
    ensure.add_argument("--secret-env", default="WORKER_SECRET", help="variable holding the secret")
    reset = sub.add_parser("reset-device-secret", help="give a device's worker a new secret")
    reset.add_argument("--name", required=True)
    hook = sub.add_parser(
        "webhook-info",
        help="print the webhook URL and signing key for a device served by an Android phone",
    )
    hook.add_argument("--name", required=True, help="the device's name")
    hook.add_argument(
        "--base-url",
        required=True,
        help="the public https address of the API as the phone reaches it, e.g. https://sms.example.com/api",
    )
    args = parser.parse_args(argv)

    if args.command == "register-device":
        secret = new_secret()
        with SessionLocal() as db:
            try:
                dev = register_device(db, args.name, args.phone, secret=secret)
            except DeviceError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        _show_secret(dev.name, secret, f"registered (id {dev.id})")
        return 0

    if args.command == "ensure-device":
        secret = os.environ.get(args.secret_env, "")
        if not secret:
            print(f"error: set {args.secret_env} to the worker's secret", file=sys.stderr)
            return 1
        with SessionLocal() as db:
            try:
                dev, created = ensure_device(db, args.name, args.phone, secret)
            except DeviceError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        print(f"{'created' if created else 'updated'} device '{dev.name}' (id {dev.id})")
        return 0

    if args.command == "reset-device-secret":
        with SessionLocal() as db:
            try:
                secret = set_device_secret(db, args.name)
            except DeviceError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        _show_secret(args.name, secret, "new secret for")
        return 0

    if args.command == "webhook-info":
        with SessionLocal() as db:
            device = db.scalars(select(GsmDevice).where(GsmDevice.name == args.name)).first()
            if device is None:
                print(f"error: unknown device {args.name!r}", file=sys.stderr)
                return 1
            device_id = device.id
        url = f"{args.base_url.rstrip('/')}/devices/{device_id}/webhook"
        print(f"Webhook URL (must be https, or the phone refuses it):\n  {url}")
        print(
            f"Signing key (Settings > Webhooks > Signing Key in the app):\n  {webhooks.device_key(device_id)}"
        )
        print("Register a webhook to that URL for each of these events in the app:")
        print("  sms:received   (messages the phone receives)")
        print("  sms:delivered  (delivery reports)")
        print("  sms:failed     (messages the carrier could not deliver)")
        return 0

    # ADMIN_PASSWORD allows non-interactive use; otherwise prompt so it never hits shell history.
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password: ")
    with SessionLocal() as db:
        try:
            user = create_admin(db, args.username, password, args.name or args.username)
        except BootstrapError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    print(f"created admin '{user.username}' (id {user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
