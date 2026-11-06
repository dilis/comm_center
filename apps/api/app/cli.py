"""Admin commands: ``python -m app.cli create-admin --username NAME``."""

import argparse
import getpass
import os
import sys

from app.bootstrap import BootstrapError, create_admin
from app.db import SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create the first administrator")
    admin.add_argument("--username", required=True)
    admin.add_argument("--name", help="display name (defaults to the username)")
    args = parser.parse_args(argv)

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
