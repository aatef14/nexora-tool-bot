"""Nexo Poll — create a native Telegram poll from a text command.

Uses Telegram's built-in Message.reply_poll, no external dependencies.
"""

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Poll"
SLUG = "poll"
COMMAND = "poll"
EMOJI = "📊"
SUMMARY = "Create a Telegram poll from a text prompt."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Create a native Telegram poll from a text command.\n\n"
    "Syntax: /poll Question? | Option A | Option B | Option C\n"
    "Pipe-separated: the first segment is the question, the rest are "
    "options (between 2 and 10 of them, Telegram's limit).\n\n"
    "Polls are anonymous by default, matching Telegram's own default "
    "(nobody can see who voted for what). Add | public as the very last "
    "segment to make the poll non-anonymous (shows who voted for what):\n"
    "/poll Best day? | Mon | Tue | Wed | public\n\n"
    "Questions are truncated to 300 characters and options to 100 "
    "characters if they run over Telegram's limits."
)

QUESTION_MAX_LEN = 300
OPTION_MAX_LEN = 100
MIN_OPTIONS = 2
MAX_OPTIONS = 10

USAGE_ERROR = (
    "Please use: /poll Question? | Option A | Option B (2-10 options)\n\n"
    f"Send /{COMMAND} for full usage."
)


def parse_poll_command(text: str) -> tuple[str, list[str], bool]:
    """Parse the text of a /poll command into (question, options, is_anonymous).

    Raises ValueError on invalid input (missing question, or fewer than
    2 / more than 10 options).
    """
    # Strip the leading "/poll" or "/poll@botname" token.
    remainder = text.strip()
    if remainder.startswith("/"):
        parts = remainder.split(maxsplit=1)
        remainder = parts[1] if len(parts) > 1 else ""

    segments = [seg.strip() for seg in remainder.split("|")]
    segments = [seg for seg in segments if seg]

    is_anonymous = True
    if segments and segments[-1].lower() == "public":
        is_anonymous = False
        segments = segments[:-1]

    if len(segments) < 1:
        raise ValueError("No question provided.")

    question = segments[0][:QUESTION_MAX_LEN]
    options = [seg[:OPTION_MAX_LEN] for seg in segments[1:]]

    if len(options) < MIN_OPTIONS:
        raise ValueError("Need at least 2 options.")
    if len(options) > MAX_OPTIONS:
        options = options[:MAX_OPTIONS]

    return question, options, is_anonymous


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    if not is_allowed(update.effective_user.id):
        await message.reply_text(PRIVATE_MESSAGE)
        return

    text = message.text or ""

    try:
        question, options, is_anonymous = parse_poll_command(text)
    except ValueError:
        await message.reply_text(USAGE_ERROR)
        return

    await message.reply_poll(question=question, options=options, is_anonymous=is_anonymous)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
