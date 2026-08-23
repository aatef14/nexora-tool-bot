"""Nexo Notes — quick personal per-user notes, persisted to a local JSON
file so they survive a bot restart.
"""

import json
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Notes"
SLUG = "notes"
COMMAND = "notes"
EMOJI = "📝"
SUMMARY = "Quick personal notes — add, list, delete, per user."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "/notes add <text> — save a new note\n"
    "/notes list — show your notes, numbered\n"
    "/notes del <number> — delete the note with that number\n"
    "/notes clear — delete all of your notes"
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
NOTES_FILE = os.path.join(DATA_DIR, "notes.json")


def _load() -> dict:
    try:
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(NOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def add_note(user_id: str, text: str) -> int:
    """Append a note for user_id, save, and return its 1-indexed position."""
    data = _load()
    notes = data.setdefault(user_id, [])
    notes.append(text)
    _save(data)
    return len(notes)


def list_notes(user_id: str) -> list[str]:
    data = _load()
    return list(data.get(user_id, []))


def delete_note(user_id: str, index: int) -> str | None:
    """Delete the 1-indexed note at index for user_id. Returns the deleted
    note's text, or None if the index is out of range."""
    data = _load()
    notes = data.get(user_id, [])
    if index < 1 or index > len(notes):
        return None
    removed = notes.pop(index - 1)
    data[user_id] = notes
    _save(data)
    return removed


def clear_notes(user_id: str) -> int:
    """Delete all notes for user_id. Returns how many were removed."""
    data = _load()
    notes = data.get(user_id, [])
    count = len(notes)
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
        text = " ".join(args[1:]).strip()
        if not text:
            await message.reply_text("Please include the note text, e.g. /notes add Buy milk")
            return
        position = add_note(user_id, text)
        await message.reply_text(f"Saved as note #{position}.")

    elif sub == "list":
        notes = list_notes(user_id)
        if not notes:
            await message.reply_text("You have no notes yet.")
            return
        lines = [f"{i}. {note}" for i, note in enumerate(notes, start=1)]
        await message.reply_text("\n".join(lines))

    elif sub == "del":
        if len(args) < 2 or not args[1].isdigit():
            await message.reply_text("Please give the note number to delete, e.g. /notes del 2")
            return
        index = int(args[1])
        removed = delete_note(user_id, index)
        if removed is None:
            await message.reply_text(f"No note #{index}. Use /notes list to see your notes.")
            return
        await message.reply_text(f"Deleted note #{index}: {removed}")

    elif sub == "clear":
        count = clear_notes(user_id)
        if count == 0:
            await message.reply_text("You have no notes to clear.")
        else:
            await message.reply_text(f"Cleared {count} note(s).")

    else:
        await message.reply_text(USAGE)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
