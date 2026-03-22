"""CLI management commands for Claude Todo backend."""

import argparse
import asyncio
import getpass
import json
import sys
from datetime import datetime

from .core.config import settings
from .core.database import connect, close_db, get_mongo_client
from .core.security import hash_password
from .models.user import AuthType, User

BACKUP_COLLECTIONS = ["users", "projects", "tasks", "allowed_emails", "mcp_api_keys"]


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


async def _backup(output_path: str) -> None:
    """Export all collections to a JSON file."""
    from bson import json_util

    await connect()
    try:
        client = get_mongo_client()
        db = client[settings.MONGO_DBNAME]
        data: dict[str, list] = {}
        total = 0
        for name in BACKUP_COLLECTIONS:
            docs = await db[name].find().to_list(None)
            data[name] = docs
            total += len(docs)
            print(f"  {name}: {len(docs)} documents")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, default=json_util.default, ensure_ascii=False, indent=2)
        print(f"Backup saved to {output_path} ({total} documents total)")
    finally:
        await close_db()


async def _restore(input_path: str) -> None:
    """Restore all collections from a JSON backup file."""
    from bson import json_util

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f, object_hook=json_util.object_hook)

    await connect()
    try:
        client = get_mongo_client()
        db = client[settings.MONGO_DBNAME]
        total = 0
        for name, docs in data.items():
            if name not in BACKUP_COLLECTIONS:
                print(f"  {name}: skipped (unknown collection)")
                continue
            await db[name].delete_many({})
            if docs:
                await db[name].insert_many(docs)
            total += len(docs)
            print(f"  {name}: {len(docs)} documents restored")
        print(f"Restore completed ({total} documents total)")
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

    backup_cmd = sub.add_parser("backup", help="Export all data to JSON")
    backup_cmd.add_argument("--output", "-o", help="Output file path")

    restore_cmd = sub.add_parser("restore", help="Restore data from JSON backup")
    restore_cmd.add_argument("input", help="Backup file path")
    restore_cmd.add_argument(
        "--confirm", action="store_true", required=True,
        help="Confirm data replacement",
    )

    args = parser.parse_args()

    if args.command == "init-admin":
        email = _resolve_value(args.email, settings.INIT_ADMIN_EMAIL, "Admin email")
        password = _resolve_value(args.password, settings.INIT_ADMIN_PASSWORD, "Admin password", secret=True)

        if len(password) < 6:
            print("Error: password must be at least 6 characters", file=sys.stderr)
            sys.exit(1)

        asyncio.run(_init_admin(email, password, args.name))

    elif args.command == "backup":
        output = args.output or f"backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        asyncio.run(_backup(output))

    elif args.command == "restore":
        asyncio.run(_restore(args.input))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
