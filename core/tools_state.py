"""Runtime state for tools: per-tool enable/disable toggle and usage
stats. Lives in data/tools_state.json (git-ignored). Checked/updated live
on every tool invocation via the gating wrapper in bot.py (see
register_tool_gated) — so toggling a tool off/on from the Admin Portal
takes effect immediately, with no bot restart and no re-registering any
Telegram handlers.
"""

import json
import os
from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
STATE_FILE = os.path.join(DATA_DIR, "tools_state.json")


def _load() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("disabled", [])
    data.setdefault("usage", {})
    return data


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def is_tool_enabled(slug: str) -> bool:
    return slug not in _load()["disabled"]


def get_disabled_tools() -> list[str]:
    return list(_load()["disabled"])


def disable_tool(slug: str) -> bool:
    """Returns False if it was already disabled (no-op)."""
    data = _load()
    if slug in data["disabled"]:
        return False
    data["disabled"].append(slug)
    _save(data)
    return True


def enable_tool(slug: str) -> bool:
    """Returns False if it was already enabled (no-op)."""
    data = _load()
    if slug not in data["disabled"]:
        return False
    data["disabled"].remove(slug)
    _save(data)
    return True


def record_usage(slug: str, user_id: int) -> None:
    data = _load()
    entry = data["usage"].setdefault(slug, {"count": 0, "users": {}, "last_used": None})
    entry["count"] += 1
    entry["last_used"] = datetime.now(timezone.utc).isoformat()
    uid_key = str(user_id)
    entry["users"][uid_key] = entry["users"].get(uid_key, 0) + 1
    _save(data)


def get_usage_stats() -> dict:
    return _load()["usage"]
