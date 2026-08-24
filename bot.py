"""Nexora Tool Bot — a multi-tool Telegram bot.

Core responsibilities only: startup, access-gated /start & /id, dispatching
to tool modules, and shared housekeeping (log rotation, cleanup jobs). All
actual feature logic lives under tools/ — see tools/__init__.py to add one.
"""

import asyncio
import logging
import os
import time

from dotenv import load_dotenv
from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from core.access import (
    ADMIN_ONLY_MESSAGE,
    ADMIN_USER_IDS,
    ALLOWED_USER_IDS,
    approve_request,
    get_admin_entries,
    get_allowed_entries,
    get_requests,
    is_admin,
    remove_request,
)
from core.tools_state import get_disabled_tools, is_tool_enabled, record_usage
from tools import TOOLS

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_NAME = "Nexora Tool Bot"
OWNER_CONTACT = os.environ.get("OWNER_CONTACT", "Atif")

MAX_LOG_SIZE_MB = int(os.environ.get("MAX_LOG_SIZE_MB", "20"))
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.log")
CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60

START_TIME = time.time()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("nexora-tool-bot")


def build_tools_text() -> str:
    disabled = set(get_disabled_tools())
    lines = ["Available tools:\n"]
    for tool in TOOLS:
        suffix = " (currently disabled by the admin)" if tool.SLUG in disabled else ""
        lines.append(f"{tool.EMOJI} /{tool.COMMAND} — {tool.NAME}: {tool.SUMMARY}{suffix}")
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
    lines.append("\nSend this ID to the bot owner to be added to the whitelist.")
    await update.effective_message.reply_text("\n".join(lines))


def human_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def human_size(num_bytes: int) -> str:
    size_kb = num_bytes / 1024
    if size_kb < 1024:
        return f"{size_kb:.0f}KB"
    return f"{size_kb / 1024:.1f}MB"


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(ADMIN_ONLY_MESSAGE)
        return

    log_size = os.path.getsize(LOG_PATH) if os.path.exists(LOG_PATH) else 0
    allowed_count = len(get_allowed_entries())
    disabled_tools = get_disabled_tools()
    pending_count = len(get_requests())
    lines = [
        f"📊 {BOT_NAME} status\n",
        f"Uptime: {human_uptime(time.time() - START_TIME)}",
        f"Tools loaded: {len(TOOLS)}" + (f" ({len(disabled_tools)} disabled)" if disabled_tools else ""),
        f"Whitelist: {'open to everyone' if allowed_count == 0 else f'{allowed_count} user(s)'}",
        f"Admins: {len(get_admin_entries())} user(s)",
        f"Pending requests: {pending_count}" + (" — send /request_list" if pending_count else ""),
        f"Log size: {human_size(log_size)} / {MAX_LOG_SIZE_MB}MB",
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def request_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(ADMIN_ONLY_MESSAGE)
        return

    pending = get_requests()
    if not pending:
        await update.effective_message.reply_text("No pending access requests.")
        return

    for r in pending:
        label = r.get("name") or str(r["id"])
        username_part = f" (@{r['username']})" if r.get("username") else ""
        requested_at = (r.get("requested_at") or "")[:16].replace("T", " ")
        text = f"👤 {label}{username_part}\nID: {r['id']}\nRequested: {requested_at}"
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"reqlist:approve:{r['id']}"),
                    InlineKeyboardButton("❌ Deny", callback_data=f"reqlist:deny:{r['id']}"),
                ]
            ]
        )
        await update.effective_message.reply_text(text, reply_markup=keyboard)


async def request_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        await query.edit_message_text(ADMIN_ONLY_MESSAGE)
        return

    _, action, user_id_str = query.data.split(":")
    user_id = int(user_id_str)

    if action == "approve":
        if approve_request(user_id):
            await query.edit_message_text(f"✅ Approved {user_id}. Added to the whitelist — takes effect immediately.")
        else:
            await query.edit_message_text("That request is no longer there (already handled).")
    else:
        if remove_request(user_id):
            await query.edit_message_text(f"❌ Denied {user_id}.")
        else:
            await query.edit_message_text("That request is no longer there (already handled).")


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

    # /status is deliberately left out of the default command list above so
    # it doesn't show up in the "/" menu for regular users — only admins get
    # it added to their own menu, via a per-chat command scope. This is just
    # a UI nicety; the actual enforcement is the is_admin() check in
    # status_command itself, which applies regardless of this scope.
    admin_commands = commands + [
        BotCommand("status", "Bot status (admin only)"),
        BotCommand("request_list", "Review pending access requests (admin only)"),
    ]
    for admin_id in ADMIN_USER_IDS:
        await _try_bot_info_call(
            f"set_my_commands (admin scope {admin_id})",
            app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id)),
        )


def register_tool_gated(app: Application, tool) -> None:
    """Registers a tool's handlers, then wraps each one so it checks
    is_tool_enabled() live before running — instead of editing every tool
    file to add that check, this diffs app.handlers before/after
    tool.register(app) to find exactly the handlers that call just added,
    and patches their callback in place. This also records usage stats
    centrally, so no tool file needs to know about that either.

    Because the check happens on every invocation (not once at startup),
    toggling a tool off/on via the Admin Portal takes effect immediately —
    no bot restart, no handler re-registration."""
    before = {group: list(handlers) for group, handlers in app.handlers.items()}
    tool.register(app)

    for group, handlers in app.handlers.items():
        prior = before.get(group, [])
        for handler in handlers:
            if handler in prior:
                continue
            original_callback = handler.callback

            async def gated_callback(update, context, _orig=original_callback, _tool=tool):
                if not is_tool_enabled(_tool.SLUG):
                    text = f"⚠️ {_tool.NAME} is currently disabled by the admin. Try again later."
                    if update.callback_query:
                        await update.callback_query.answer(text, show_alert=True)
                    else:
                        await update.effective_message.reply_text(text)
                    return
                user = update.effective_user
                if user:
                    record_usage(_tool.SLUG, user.id)
                await _orig(update, context)

            handler.callback = gated_callback


def main() -> None:
    # Python 3.14 dropped asyncio.get_event_loop()'s auto-create behavior,
    # which python-telegram-bot's run_polling() still relies on internally.
    # https://github.com/python-telegram-bot/python-telegram-bot/issues/4874
    asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(BOT_TOKEN).post_init(set_bot_info).build()
    app.add_handler(CommandHandler(["start", "help"], start_command))
    app.add_handler(CommandHandler("tools", tools_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("request_list", request_list_command))
    app.add_handler(CallbackQueryHandler(request_list_callback, pattern=r"^reqlist:"))
    for tool in TOOLS:
        register_tool_gated(app, tool)
    app.add_error_handler(error_handler)
    app.job_queue.run_repeating(daily_cleanup, interval=CLEANUP_INTERVAL_SECONDS, first=60)

    logger.info(
        "%s starting with tools: %s (whitelist: %s, admins: %d)",
        BOT_NAME,
        ", ".join(t.NAME for t in TOOLS),
        "open" if ALLOWED_USER_IDS is None else f"{len(ALLOWED_USER_IDS)} user(s)",
        len(ADMIN_USER_IDS),
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
