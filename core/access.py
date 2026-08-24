"""Shared access control, used by every tool module.

ALLOWED_USER_IDS is a single whitelist for the whole bot (not per-tool) —
if you're allowed to use the bot at all, you're allowed to use every tool
in it. ADMIN_USER_IDS is a separate, stricter list for admin-only commands
(e.g. /status) — being on the general whitelist does NOT imply admin.
"""

import os


def _parse_user_ids(raw: str):
    # Entries are "id" or "id:Name" (the name is just a label for the admin
    # web UI and is ignored here).
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    return {int(e.split(":", 1)[0]) for e in entries}


_allowed_ids = _parse_user_ids(os.environ.get("ALLOWED_USER_IDS", "").strip())
# Unset/blank ALLOWED_USER_IDS means "open to everyone" (None), matching the
# bot's long-standing default — deliberately permissive since that's the
# out-of-the-box behavior documented in the README.
ALLOWED_USER_IDS = _allowed_ids or None

# Unset/blank ADMIN_USER_IDS means "no admins" (fail closed) — admin-only
# commands should never default to open, unlike the general whitelist above.
ADMIN_USER_IDS = _parse_user_ids(os.environ.get("ADMIN_USER_IDS", "").strip())

PRIVATE_MESSAGE = (
    "This bot is private.\n\n"
    "Send /id to get your Telegram user ID, then send that ID to the bot "
    "owner and ask them to add it to ALLOWED_USER_IDS."
)

ADMIN_ONLY_MESSAGE = "This command is for the bot admin only."


def is_allowed(user_id: int) -> bool:
    return ALLOWED_USER_IDS is None or user_id in ALLOWED_USER_IDS


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS
