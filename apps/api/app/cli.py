"""Admin commands: ``create-admin``, ``create-worker``, ``ensure-worker``, ``register-device``,
``assign-device`` and ``webhook-info``
(``python -m app.cli --help``)."""

import argparse
import getpass
import json
import os
import sys

from sqlalchemy import select

from app import webhooks
from app.bootstrap import BootstrapError, create_admin
from app.db import SessionLocal
from app.devices import PROVIDERS, DeviceError, assign_device, ensure_fake_device, register_device
from app.models import GsmDevice
from app.worker_accounts import WorkerError, create_worker, ensure_worker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create the first administrator")
    admin.add_argument("--username", required=True)
    admin.add_argument("--name", help="display name (defaults to the username)")
    worker = sub.add_parser("create-worker", help="register a worker program and print its secret")
    worker.add_argument("--name", required=True, help="short unique name the worker signs in with")
    ensure = sub.add_parser(
        "ensure-worker",
        help="create a worker (or reset its secret) with the secret from an environment variable",
    )
    ensure.add_argument("--name", required=True)
    ensure.add_argument("--secret-env", default="WORKER_SECRET", help="variable holding the secret")
    ensure.add_argument(
        "--fake-device", action="store_true", help="if no device exists, add a fake one for it"
    )
    device = sub.add_parser("register-device", help="register a GSM device and its inbound agent")
    device.add_argument("--name", required=True, help="short unique name; the agent is gsm-<name>")
    device.add_argument("--serial-port", required=True, help="e.g. /dev/ttyUSB0")
    device.add_argument("--phone", required=True, help="the SIM's own number")
    device.add_argument("--provider", choices=PROVIDERS, default="fake")
    device.add_argument(
        "--config",
        default="{}",
        help='JSON object, no secrets, e.g. \'{"base_url": "http://10.0.0.5:8080"}\'',
    )
    device.add_argument("--worker", help="name of the worker that serves this device")
    assign = sub.add_parser("assign-device", help="give an existing device to a worker")
    assign.add_argument("--name", required=True, help="the device's name")
    assign.add_argument("--worker", required=True, help="the worker account that will serve it")
    assign.add_argument("--provider", choices=PROVIDERS, help="change the provider too")
    assign.add_argument("--config", help="replace the config with this JSON object")
    hook = sub.add_parser(
        "webhook-info", help="print the webhook URL and signing key for an Android device"
    )
    hook.add_argument("--name", required=True, help="the device's name")
    hook.add_argument(
        "--base-url",
        required=True,
        help="the public https address of the API as the phone reaches it, e.g. https://sms.example.com/api",
    )
    args = parser.parse_args(argv)

    if args.command == "create-worker":
        with SessionLocal() as db:
            try:
                created, secret = create_worker(db, args.name)
            except WorkerError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        print(f"created worker '{created.name}' (id {created.id}). Its secret is shown only now:")
        print(secret)
        return 0

    if args.command == "ensure-worker":
        secret = os.environ.get(args.secret_env, "")
        if not secret:
            print(f"error: set {args.secret_env} to the worker's secret", file=sys.stderr)
            return 1
        with SessionLocal() as db:
            try:
                ensured, created = ensure_worker(db, args.name, secret)
                fake = ensure_fake_device(db, ensured.name) if args.fake_device else None
            except (WorkerError, DeviceError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        print(f"{'created' if created else 'updated'} worker '{ensured.name}' (id {ensured.id})")
        if fake:
            print(f"registered fake device '{fake.name}' for it")
        return 0

    if args.command == "webhook-info":
        with SessionLocal() as db:
            device = db.scalars(select(GsmDevice).where(GsmDevice.name == args.name)).first()
            if device is None:
                print(f"error: unknown device {args.name!r}", file=sys.stderr)
                return 1
            if device.provider != "android":
                print(
                    f"error: {args.name!r} is a {device.provider} device, not android",
                    file=sys.stderr,
                )
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

    if args.command == "assign-device":
        config = None
        if args.config is not None:
            try:
                config = json.loads(args.config)
            except ValueError:
                config = None
            if not isinstance(config, dict):
                print("error: --config must be a JSON object", file=sys.stderr)
                return 1
        with SessionLocal() as db:
            try:
                dev = assign_device(
                    db, args.name, args.worker, provider=args.provider, config=config
                )
            except DeviceError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        print(
            f"device '{dev.name}' now belongs to worker '{args.worker}' (provider {dev.provider})"
        )
        return 0

    if args.command == "register-device":
        try:
            config = json.loads(args.config)
        except ValueError:
            config = None
        if not isinstance(config, dict):
            print("error: --config must be a JSON object", file=sys.stderr)
            return 1
        with SessionLocal() as db:
            try:
                dev = register_device(
                    db, args.name, args.serial_port, args.phone,
                    provider=args.provider, config=config, worker=args.worker,
                )  # fmt: skip
            except DeviceError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        print(f"registered device '{dev.name}' (id {dev.id}, agent user {dev.agent_user_id})")
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
