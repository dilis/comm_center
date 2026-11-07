"""Admin commands: ``create-admin`` and ``register-device`` (``python -m app.cli --help``)."""

import argparse
import getpass
import os
import sys

from app.bootstrap import BootstrapError, create_admin
from app.db import SessionLocal
from app.devices import DeviceError, register_device


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create the first administrator")
    admin.add_argument("--username", required=True)
    admin.add_argument("--name", help="display name (defaults to the username)")
    device = sub.add_parser("register-device", help="register a GSM device and its inbound agent")
    device.add_argument("--name", required=True, help="short unique name; the agent is gsm-<name>")
    device.add_argument("--serial-port", required=True, help="e.g. /dev/ttyUSB0")
    device.add_argument("--phone", required=True, help="the SIM's own number")
    args = parser.parse_args(argv)

    if args.command == "register-device":
        with SessionLocal() as db:
            try:
                dev = register_device(db, args.name, args.serial_port, args.phone)
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
