"""Nexo Password — generates strong random passwords."""

import secrets
import string

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Password"
SLUG = "password"
COMMAND = "password"
EMOJI = "🔐"
SUMMARY = "Generate a strong random password."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "/password - generate a strong 16-character password (letters, digits, symbols).\n"
    "/password <length> - generate a password of the given length (8-128).\n"
    "/password <length> nosymbols - exclude symbols from the generated password."
)

MIN_LENGTH = 8
MAX_LENGTH = 128
DEFAULT_LENGTH = 16

LOWERCASE = string.ascii_lowercase
UPPERCASE = string.ascii_uppercase
DIGITS = string.digits
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?"

_random = secrets.SystemRandom()


def generate_password(length: int, use_symbols: bool = True) -> str:
    """Generate a cryptographically secure random password of the given
    length, guaranteeing at least one character from each included
    category (lowercase, uppercase, digits, and optionally symbols)."""
    if length < MIN_LENGTH or length > MAX_LENGTH:
        raise ValueError(f"length must be between {MIN_LENGTH} and {MAX_LENGTH}")

    categories = [LOWERCASE, UPPERCASE, DIGITS]
    if use_symbols:
        categories.append(SYMBOLS)

    # Guarantee at least one character from each category.
    password_chars = [secrets.choice(category) for category in categories]

    all_chars = "".join(categories)
    remaining = length - len(password_chars)
    password_chars.extend(secrets.choice(all_chars) for _ in range(remaining))

    _random.shuffle(password_chars)
    return "".join(password_chars)


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(PRIVATE_MESSAGE)
        return

    args = context.args or []
    length = DEFAULT_LENGTH
    use_symbols = True

    if len(args) >= 1:
        raw_length = args[0]
        if not raw_length.isdigit():
            await update.effective_message.reply_text(
                f"Length must be a number between {MIN_LENGTH} and {MAX_LENGTH}."
            )
            return
        length = int(raw_length)
        if length < MIN_LENGTH or length > MAX_LENGTH:
            await update.effective_message.reply_text(
                f"Length must be between {MIN_LENGTH} and {MAX_LENGTH}."
            )
            return

    if len(args) >= 2 and args[1].lower() == "nosymbols":
        use_symbols = False

    password = generate_password(length, use_symbols)
    await update.effective_message.reply_text(f"Your password:\n\n{password}")


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
