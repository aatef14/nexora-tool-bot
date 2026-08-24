"""Nexora Tool Bot — a multi-tool Telegram bot.

Core responsibilities only: startup, access-gated /start & /id, dispatching
to tool modules, and shared housekeeping (log rotation, cleanup jobs). All
actual feature logic lives under tools/ — see tools/__init__.py to add one.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import ALLOWED_USER_IDS
from tools import TOOLS

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_NAME = "Nexora Tool Bot"
OWNER_CONTACT = os.environ.get("OWNER_CONTACT", "Atif")

MAX_LOG_SIZE_MB = int(os.environ.get("MAX_LOG_SIZE_MB", "20"))
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("nexora-tool-bot")


def build_tools_text() -> str:
    lines = ["Available tools:\n"]
    for tool in TOOLS:
        lines.append(f"{tool.EMOJI} /{tool.COMMAND} — {tool.NAME}: {tool.SUMMARY}")
    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        f"{BOT_NAME}\n\n"
        "A growing collection of utility tools in one bot.\n\n"
        "Send /tools to see everything available, or /id to get your "
        "Telegram user ID."
    )


async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(build_tools_text())


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    lines = [f"Your Telegram user ID: {user.id}"]
    if user.username:
        lines.append(f"Username: @{user.username}")
    lines.append("\nAdd this ID to ALLOWED_USER_IDS in .env to whitelist yourself.")
    await update.effective_message.reply_text("\n".join(lines))


def rotate_log_if_large() -> None:
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_LOG_SIZE_MB * 1024 * 1024:
            open(LOG_PATH, "w").close()
            logger.info("Truncated bot.log after exceeding %sMB", MAX_LOG_SIZE_MB)
    except OSError:
        pass


async def daily_cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    for tool in TOOLS:
        cleanup = getattr(tool, "cleanup", None)
        if not cleanup:
            continue
        removed = cleanup()
        if removed:
            logger.info("%s cleanup removed %d stale item(s)", tool.NAME, removed)
    rotate_log_if_large()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Network blips during polling (phone briefly losing signal/WiFi) are
    # normal and self-recovering, so log them as a one-liner instead of a
    # full traceback that makes it look like the bot crashed.
    logger.warning("Update handling error: %s", context.error)

    # Whatever went wrong, the person who sent this update deserves *some*
    # reply instead of silence — but this can only fire if the phone's own
    # connection is up long enough to receive their message and send a
    # reply in the first place. If the phone is genuinely offline, nothing
    # (bot included) can respond until it's back — that's not fixable from
    # inside the bot.
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"⚠️ Server busy right now — please try again shortly, or message {OWNER_CONTACT}.",
            )
        except Exception:
            pass  # if even this fails, there's nothing more we can do here


async def _try_bot_info_call(label: str, coro) -> None:
    """Run a set_my_* bot-profile call, but never let it block startup.
    These are purely cosmetic (command menu, name, description shown in the
    Telegram UI) — not required for the bot to actually process updates —
    so a transient failure (e.g. Telegram's flood control after repeated
    restarts) should log a warning and move on, not crash the whole bot."""
    try:
        await coro
    except Exception as e:
        logger.warning("Skipping %s (non-fatal): %s", label, e)


async def set_bot_info(app: Application) -> None:
    commands = [
        BotCommand("start", "About this bot"),
        BotCommand("tools", "List all available tools"),
        BotCommand("help", "About this bot"),
        BotCommand("id", "Show your Telegram user ID"),
    ]
    for tool in TOOLS:
        commands.append(BotCommand(tool.COMMAND, tool.NAME))

    # Telegram caps set_my_description at 512 chars and set_my_short_description
    # at 120 — listing every tool by name doesn't scale as more get added, so
    # just state the count and point to /tools for the actual list.
    description = (
        f"{BOT_NAME}: a growing collection of utility tools in one bot "
        f"({len(TOOLS)} so far). Send /tools in a chat with the bot to see "
        "the full list."
    )
    short_description = f"{BOT_NAME}: {len(TOOLS)} utility tools. Send /tools for the list."

    await _try_bot_info_call("set_my_commands", app.bot.set_my_commands(commands))
    await _try_bot_info_call("set_my_name", app.bot.set_my_name(BOT_NAME))
    await _try_bot_info_call("set_my_description", app.bot.set_my_description(description[:512]))
    await _try_bot_info_call(
        "set_my_short_description", app.bot.set_my_short_description(short_description[:120])
    )


def main() -> None:
    # Python 3.14 dropped asyncio.get_event_loop()'s auto-create behavior,
    # which python-telegram-bot's run_polling() still relies on internally.
    # https://github.com/python-telegram-bot/python-telegram-bot/issues/4874
    asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(BOT_TOKEN).post_init(set_bot_info).build()
    app.add_handler(CommandHandler(["start", "help"], start_command))
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("id", id_command))
    for tool in TOOLS:
        tool.register(app)
    app.add_error_handler(error_handler)
    app.job_queue.run_repeating(daily_cleanup, interval=CLEANUP_INTERVAL_SECONDS, first=60)

    logger.info(
        "%s starting with tools: %s (whitelist: %s)",
        BOT_NAME,
        ", ".join(t.NAME for t in TOOLS),
        "open" if ALLOWED_USER_IDS is None else f"{len(ALLOWED_USER_IDS)} user(s)",
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
