"""Shared access control, used by every tool module.

ALLOWED_USER_IDS is a single whitelist for the whole bot (not per-tool) —
if you're allowed to use the bot at all, you're allowed to use every tool
in it.
"""

import os


def _parse_allowed_user_ids(raw: str):
    # Entries are "id" or "id:Name" (the name is just a label for the admin
    # web UI and is ignored here).
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    if not entries:
        return None
    return {int(e.split(":", 1)[0]) for e in entries}


ALLOWED_USER_IDS = _parse_allowed_user_ids(os.environ.get("ALLOWED_USER_IDS", "").strip())

PRIVATE_MESSAGE = (
    "This bot is private.\n\n"
    "Send /id to get your Telegram user ID, then send that ID to the bot "
    "owner and ask them to add it to ALLOWED_USER_IDS."
)


def is_allowed(user_id: int) -> bool:
    return ALLOWED_USER_IDS is None or user_id in ALLOWED_USER_IDS
