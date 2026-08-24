"""Shared access control, used by every tool module.

The whitelist and admin list live in data/access.json (git-ignored, holds
real Telegram user IDs) — not in .env, so the web Admin Portal can manage
them as simple data instead of parsing/rewriting unrelated bot config.

ALLOWED_USER_IDS is a single whitelist for the whole bot (not per-tool) —
if you're allowed to use the bot at all, you're allowed to use every tool
in it. ADMIN_USER_IDS is a separate, stricter list for admin-only commands
(e.g. /status) — being on the general whitelist does NOT imply admin.
"""

import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ACCESS_FILE = os.path.join(DATA_DIR, "access.json")


def _parse_env_user_ids(raw: str) -> list[dict]:
    # Legacy "id" or "id:Name" comma-separated format, from before the
    # whitelist/admin list moved out of .env into ACCESS_FILE.
    entries = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        uid, _, name = part.partition(":")
        uid = uid.strip()
        if uid.isdigit():
            entries.append({"id": int(uid), "name": name.strip()})
    return entries


def _migrate_from_env() -> dict:
    """One-time migration: if ACCESS_FILE doesn't exist yet but the old
    ALLOWED_USER_IDS/ADMIN_USER_IDS env vars are set, carry them over so an
    existing setup doesn't silently lose its whitelist. Writes the file so
    this only ever runs once; a fresh install with neither set just starts
    with empty lists without creating the file yet."""
    allowed = _parse_env_user_ids(os.environ.get("ALLOWED_USER_IDS", ""))
    admins = _parse_env_user_ids(os.environ.get("ADMIN_USER_IDS", ""))
    data = {"allowed": allowed, "admins": admins}
    if allowed or admins:
        _save_access(data)
    return data


def _load_access() -> dict:
    if not os.path.exists(ACCESS_FILE):
        return _migrate_from_env()
    try:
        with open(ACCESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"allowed": [], "admins": []}
    data.setdefault("allowed", [])
    data.setdefault("admins", [])
    return data


def _save_access(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACCESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _add_entry(list_key: str, user_id: int, name: str) -> bool:
    """Add user_id to data[list_key] if not already present. Returns False
    if it was already there (no-op), True if added."""
    data = _load_access()
    if any(e["id"] == user_id for e in data[list_key]):
        return False
    data[list_key].append({"id": user_id, "name": name})
    _save_access(data)
    return True


def _remove_entry(list_key: str, user_id: int) -> bool:
    """Remove user_id from data[list_key]. Returns True if it was present."""
    data = _load_access()
    remaining = [e for e in data[list_key] if e["id"] != user_id]
    if len(remaining) == len(data[list_key]):
        return False
    data[list_key] = remaining
    _save_access(data)
    return True


def get_allowed_entries() -> list[dict]:
    return list(_load_access()["allowed"])


def get_admin_entries() -> list[dict]:
    return list(_load_access()["admins"])


def add_allowed(user_id: int, name: str = "") -> bool:
    return _add_entry("allowed", user_id, name)


def remove_allowed(user_id: int) -> bool:
    return _remove_entry("allowed", user_id)


def add_admin(user_id: int, name: str = "") -> bool:
    return _add_entry("admins", user_id, name)


def remove_admin(user_id: int) -> bool:
    return _remove_entry("admins", user_id)


_access = _load_access()

# Empty allowed list means "open to everyone" (None) — the bot's
# long-standing default, unchanged by this move away from .env.
ALLOWED_USER_IDS = {e["id"] for e in _access["allowed"]} or None

# Empty admin list means "no admins" (fail closed) — admin-only commands
# should never default to open, unlike the general whitelist above.
ADMIN_USER_IDS = {e["id"] for e in _access["admins"]}

PRIVATE_MESSAGE = (
    "This bot is private.\n\n"
    "Send /id to get your Telegram user ID, then send that ID to the bot "
    "owner and ask them to add it to the whitelist."
)

ADMIN_ONLY_MESSAGE = "This command is for the bot admin only."


def is_allowed(user_id: int) -> bool:
    return ALLOWED_USER_IDS is None or user_id in ALLOWED_USER_IDS


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS
