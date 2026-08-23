"""Nexo Expense — quick personal expense logging with daily/monthly
summaries, persisted to a local JSON file so entries survive a bot restart.
"""

import json
import os
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Expense"
SLUG = "expense"
COMMAND = "expense"
EMOJI = "💸"
SUMMARY = "Log quick expenses and see daily/monthly totals."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "/expense add <amount> <category/description> — log an expense, "
    "e.g. /expense add 12.50 lunch\n"
    "/expense today — show today's entries and total\n"
    "/expense month — show this month's entries grouped by category, with a total\n"
    "/expense clear — delete ALL of your logged expenses (this cannot be undone)"
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
EXPENSES_FILE = os.path.join(DATA_DIR, "expenses.json")


def _load() -> dict:
    try:
        with open(EXPENSES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(EXPENSES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def add_expense(user_id: str, amount: float, note: str) -> dict:
    """Append an expense entry for user_id, save, and return the entry."""
    data = _load()
    entries = data.setdefault(user_id, [])
    entry = {
        "amount": amount,
        "note": note,
        "timestamp": datetime.utcnow().isoformat(),
    }
    entries.append(entry)
    _save(data)
    return entry


def today_expenses(user_id: str) -> list[dict]:
    """Return this user's entries whose timestamp date matches today's UTC date."""
    data = _load()
    entries = data.get(user_id, [])
    today = datetime.utcnow().date()
    result = []
    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except (KeyError, ValueError):
            continue
        if ts.date() == today:
            result.append(entry)
    return result


def month_expenses(user_id: str) -> list[dict]:
    """Return this user's entries within the current UTC calendar month."""
    data = _load()
    entries = data.get(user_id, [])
    now = datetime.utcnow()
    result = []
    for entry in entries:
        try:
            ts = datetime.fromisoformat(entry["timestamp"])
        except (KeyError, ValueError):
            continue
        if ts.year == now.year and ts.month == now.month:
            result.append(entry)
    return result


def clear_expenses(user_id: str) -> int:
    """Delete all expenses for user_id. Returns how many were removed."""
    data = _load()
    entries = data.get(user_id, [])
    count = len(entries)
    if user_id in data:
        data[user_id] = []
        _save(data)
    return count


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(PRIVATE_MESSAGE)
        return

    message = update.effective_message
    user_id = str(update.effective_user.id)
    args = context.args or []

    if not args:
        await message.reply_text(USAGE)
        return

    sub = args[0].lower()

    if sub == "add":
        if len(args) < 2:
            await message.reply_text(
                "Please include an amount, e.g. /expense add 12.50 lunch"
            )
            return
        try:
            amount = float(args[1])
        except ValueError:
            await message.reply_text(
                f"'{args[1]}' doesn't look like a number. Try /expense add 12.50 lunch"
            )
            return
        if amount <= 0:
            await message.reply_text("Amount must be a positive number.")
            return
        note = " ".join(args[2:]).strip() or "misc"
        add_expense(user_id, amount, note)
        await message.reply_text(f"Logged ${amount:.2f} for {note}.")

    elif sub == "today":
        entries = today_expenses(user_id)
        if not entries:
            await message.reply_text("No expenses logged today.")
            return
        lines = [f"- ${e['amount']:.2f} — {e['note']}" for e in entries]
        total = sum(e["amount"] for e in entries)
        lines.append(f"\nTotal: ${total:.2f}")
        await message.reply_text("\n".join(lines))

    elif sub == "month":
        entries = month_expenses(user_id)
        if not entries:
            await message.reply_text("No expenses logged this month.")
            return
        groups: dict[str, float] = {}
        for e in entries:
            groups[e["note"]] = groups.get(e["note"], 0.0) + e["amount"]
        lines = [f"- {note}: ${amount:.2f}" for note, amount in groups.items()]
        total = sum(groups.values())
        lines.append(f"\nTotal: ${total:.2f}")
        await message.reply_text("\n".join(lines))

    elif sub == "clear":
        count = clear_expenses(user_id)
        if count == 0:
            await message.reply_text("You have no expenses to clear.")
        else:
            await message.reply_text(f"Cleared {count} expense(s).")

    else:
        await message.reply_text(USAGE)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
