"""CLI management commands for Claude Todo backend."""

import argparse
import asyncio
import getpass
import sys

from .core.config import settings
from .core.database import connect, close_db
from .core.security import hash_password
from .models.user import AuthType, User


async def create_admin_user(email: str, password: str, name: str) -> None:
    """Create an admin user. Assumes DB is already connected."""
    existing = await User.find_one(User.email == email)
    if existing:
        print(f"User already exists: {email} (admin={existing.is_admin})")
        return

    user = User(
        email=email,
        name=name,
        auth_type=AuthType.admin,
        password_hash=hash_password(password),
        is_admin=True,
        is_active=True,
    )
    await user.insert()
    print(f"Admin user created: {email}")


async def _init_admin(email: str, password: str, name: str) -> None:
    """Create an admin user with DB lifecycle management."""
    await connect()
    try:
        await create_admin_user(email, password, name)
    finally:
        await close_db()


def _resolve_value(args_val: str | None, env_val: str, prompt_msg: str, *, secret: bool = False) -> str:
    """Resolve value from: CLI arg > env var > interactive prompt."""
    if args_val:
        return args_val
    if env_val:
        return env_val
    if not sys.stdin.isatty():
        print(f"Error: {prompt_msg} is required (use argument or env var)", file=sys.stderr)
        sys.exit(1)
    if secret:
        return getpass.getpass(f"{prompt_msg}: ")
    return input(f"{prompt_msg}: ")


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Todo management CLI")
    sub = parser.add_subparsers(dest="command")

    init_cmd = sub.add_parser("init-admin", help="Create initial admin user")
    init_cmd.add_argument("--email", help="Admin email (or INIT_ADMIN_EMAIL env)")
    init_cmd.add_argument("--password", help="Admin password (or INIT_ADMIN_PASSWORD env)")
    init_cmd.add_argument("--name", default="Admin", help="Display name (default: Admin)")

    args = parser.parse_args()

    if args.command == "init-admin":
        email = _resolve_value(args.email, settings.INIT_ADMIN_EMAIL, "Admin email")
        password = _resolve_value(args.password, settings.INIT_ADMIN_PASSWORD, "Admin password", secret=True)

        if len(password) < 6:
            print("Error: password must be at least 6 characters", file=sys.stderr)
            sys.exit(1)

        asyncio.run(_init_admin(email, password, args.name))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
