"""Nexo Reminder — schedule a one-off reminder message.

Uses python-telegram-bot's JobQueue to fire a single delayed message back
into the chat that requested it.
"""

import re
import uuid

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Reminder"
SLUG = "reminder"
COMMAND = "remind"
EMOJI = "⏰"
SUMMARY = "Set a one-off reminder — /remind 10m Take the laundry out."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Usage: /remind <duration> <message>\n\n"
    "Duration is a short shorthand: a number followed by s (seconds), "
    "m (minutes), h (hours), or d (days). Max is 30 days.\n\n"
    "Examples:\n"
    "/remind 30s Check the oven\n"
    "/remind 10m Take the laundry out\n"
    "/remind 2h Call back the client\n"
    "/remind 1d Renew the domain"
)

DURATION_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)

UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
}

MAX_DURATION_SECONDS = 30 * 24 * 60 * 60  # 30 days


def parse_duration(text: str) -> int:
    """Parse a shorthand duration string like '10m', '2h', '1d', '45s'
    into a whole number of seconds.

    Raises ValueError with a clear message on anything invalid: missing
    unit, non-numeric value, zero/negative duration, or a duration beyond
    the 30-day cap.
    """
    if not text:
        raise ValueError("Duration is missing. Use a format like 10m, 2h, or 1d.")

    match = DURATION_RE.match(text)
    if not match:
        raise ValueError(
            f"Couldn't understand duration '{text}'. Use a number followed by "
            "s, m, h, or d (e.g. 30s, 10m, 2h, 1d)."
        )

    amount = int(match.group(1))
    unit = match.group(2).lower()

    if amount <= 0:
        raise ValueError("Duration must be greater than zero.")

    seconds = amount * UNIT_SECONDS[unit]

    if seconds > MAX_DURATION_SECONDS:
        raise ValueError("Duration is too long. The maximum is 30 days.")

    return seconds


def format_human_duration(seconds: int) -> str:
    """Return a short human-friendly restatement of a duration in seconds."""
    if seconds % (60 * 60 * 24) == 0 and seconds >= 60 * 60 * 24:
        value = seconds // (60 * 60 * 24)
        return f"{value}d"
    if seconds % (60 * 60) == 0 and seconds >= 60 * 60:
        value = seconds // (60 * 60)
        return f"{value}h"
    if seconds % 60 == 0 and seconds >= 60:
        value = seconds // 60
        return f"{value}m"
    return f"{seconds}s"


async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=context.job.chat_id, text=f"⏰ Reminder: {context.job.data}"
    )


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(PRIVATE_MESSAGE)
        return

    args = context.args or []
    if len(args) < 2:
        await update.effective_message.reply_text(
            "Usage: /remind <duration> <message>\n\n" + USAGE
        )
        return

    duration_text = args[0]
    reminder_text = " ".join(args[1:]).strip()

    if not reminder_text:
        await update.effective_message.reply_text(
            "Please include a message to remind you about.\n\n" + USAGE
        )
        return

    try:
        seconds = parse_duration(duration_text)
    except ValueError as e:
        await update.effective_message.reply_text(f"{e}\n\n{USAGE}")
        return

    chat_id = update.effective_chat.id
    job_id = uuid.uuid4().hex[:12]
    context.job_queue.run_once(
        send_reminder,
        when=seconds,
        chat_id=chat_id,
        data=reminder_text,
        name=f"reminder_{chat_id}_{job_id}",
    )

    human = format_human_duration(seconds)
    await update.effective_message.reply_text(
        f"Okay, I'll remind you in {human} ('{reminder_text}')."
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
