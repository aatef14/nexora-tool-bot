"""Nexo Password Manager — a per-user encrypted vault of saved logins.

Flow: /password_manager creates a vault (first time) or signs in (after),
protected by a master password that is never stored — only used to derive
an encryption key via PBKDF2, verified against a "canary" token. Signing in
opens an in-memory session that signs out automatically after 30 seconds of
inactivity; entries are listed by purpose, and revealing one shows the
username/password (auto-deleted from the chat after a short delay). Every
question the bot asks (master password, purpose, username, password) and
the answer to it are deleted from the chat the instant that step is
processed, so nothing sensitive accumulates in the chat history as you go.

There is deliberately no password recovery: forgetting the master password
means the old vault's entries can never be decrypted again. The sign-in
prompt offers a "Forgot password?" option that wipes the unreadable old
vault so a fresh one can be created — it cannot recover the old entries,
only clear the way for new ones.
"""

import base64
import json
import logging
import os
import time

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.access import deny_access, is_allowed

NAME = "Nexo Password Manager"
SLUG = "password_manager"
COMMAND = "password_manager"
EMOJI = "🔑"
SUMMARY = "An encrypted vault for saved logins — create/sign in, list, reveal, add."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "/password_manager — create your vault (first time) or sign in. "
    "Forgot your master password? There's a button for that on the sign-in "
    "prompt — it wipes the old (unreadable) vault so you can start fresh.\n\n"
    "Once signed in you'll get buttons to list saved entries, add a new one "
    "(Purpose, Username, Password — one message each), sign out, or delete "
    "the whole vault. Every question the bot asks and your answer to it "
    "are deleted from the chat immediately, so nothing lingers. Revealing "
    "an entry shows the username/password and auto-deletes after "
    "{auto_delete} seconds. Signing in expires after {session_ttl} seconds "
    "of inactivity.\n\n"
    "Your master password is never stored — only used to derive the "
    "encryption key. There is NO recovery if you forget it."
).format(auto_delete=60, session_ttl=30)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
VAULT_FILE = os.path.join(DATA_DIR, "password_manager.json")

MIN_MASTER_LENGTH = 8
SESSION_TTL_SECONDS = 30
PENDING_TTL_SECONDS = 10 * 60
REVEAL_AUTO_DELETE_SECONDS = 60
PBKDF2_ITERATIONS = 390_000
CANARY_PLAINTEXT = b"nexora-password-manager-canary"

logger = logging.getLogger("nexora-tool-bot.password_manager")

# In-memory only — never persisted. {user_id: {"key": bytes, "expires": float}}
SESSIONS: dict[str, dict] = {}
# In-memory only. {user_id: {"stage": str, "data": dict, "prompt_id": int|None, "created": float}}
PENDING: dict[str, dict] = {}


class _HasPendingInput(filters.MessageFilter):
    """Matches only messages from a user who is mid-flow with this tool
    (creating/signing into a vault, or adding an entry) — so this tool's
    text handler never swallows messages meant for other tools (e.g. a
    link for Nexo Link2video)."""

    def filter(self, message) -> bool:
        user = message.from_user
        return bool(user) and str(user.id) in PENDING


HAS_PENDING = _HasPendingInput()


def _load() -> dict:
    try:
        with open(VAULT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(VAULT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _derive_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


def _make_canary(key: bytes) -> str:
    return Fernet(key).encrypt(CANARY_PLAINTEXT).decode("ascii")


def _verify_canary(key: bytes, canary: str) -> bool:
    try:
        return Fernet(key).decrypt(canary.encode("ascii")) == CANARY_PLAINTEXT
    except InvalidToken:
        return False


def _encrypt_entry(key: bytes, entry: dict) -> str:
    return Fernet(key).encrypt(json.dumps(entry).encode("utf-8")).decode("ascii")


def _decrypt_entry(key: bytes, token: str) -> dict:
    return json.loads(Fernet(key).decrypt(token.encode("ascii")).decode("utf-8"))


def _get_valid_session(user_id: str) -> bytes | None:
    session = SESSIONS.get(user_id)
    if not session:
        return None
    if time.time() > session["expires"]:
        SESSIONS.pop(user_id, None)
        return None
    session["expires"] = time.time() + SESSION_TTL_SECONDS  # sliding refresh
    return session["key"]


def _set_session(user_id: str, key: bytes) -> None:
    SESSIONS[user_id] = {"key": key, "expires": time.time() + SESSION_TTL_SECONDS}


def _sanitize(value: str) -> str:
    # Backticks would break the Markdown code-span formatting used below.
    return value.replace("`", "'")


def _menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📋 List passwords", callback_data="pm:list")],
            [InlineKeyboardButton("➕ Add password", callback_data="pm:addstart")],
            [InlineKeyboardButton("🔒 Sign out", callback_data="pm:signout")],
            [InlineKeyboardButton("🗑 Delete vault", callback_data="pm:deleteprompt")],
        ]
    )


def _delete_vault_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⚠️ Yes, delete everything", callback_data="pm:deleteconfirm")],
            [InlineKeyboardButton("⬅ Cancel", callback_data="pm:menu")],
        ]
    )


def _signin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❓ Forgot password? Reset vault", callback_data="pm:forgotprompt")]]
    )


def _forgot_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⚠️ Yes, delete old vault & start fresh", callback_data="pm:forgotconfirm")],
            [InlineKeyboardButton("⬅ Cancel", callback_data="pm:forgotcancel")],
        ]
    )


def _list_keyboard(purposes: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"🔐 {p}", callback_data=f"pm:reveal:{i}")] for i, p in enumerate(purposes)]
    rows.append([InlineKeyboardButton("⬅ Back", callback_data="pm:menu")])
    return InlineKeyboardMarkup(rows)


def _reveal_keyboard(index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗑 Delete this entry", callback_data=f"pm:del:{index}")],
            [InlineKeyboardButton("⬅ Back to list", callback_data="pm:list")],
        ]
    )


def _format_reveal(entry: dict) -> str:
    purpose = entry.get("purpose", "")
    username = _sanitize(entry.get("username", ""))
    password = _sanitize(entry.get("password", ""))
    return (
        f"🔐 {purpose}\n\n"
        f"Username:\n`{username}`\n\n"
        f"Password:\n`{password}`\n\n"
        f"Tap either to copy. This message auto-deletes in {REVEAL_AUTO_DELETE_SECONDS}s."
    )


async def _delete_message_safe(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        logger.debug("Could not delete message %s in chat %s (probably already gone)", message_id, chat_id)


async def _auto_delete_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id, message_id = context.job.data
    await _delete_message_safe(context, chat_id, message_id)


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return

    user_id = str(update.effective_user.id)

    if _get_valid_session(user_id):
        await message.reply_text(f"{EMOJI} {NAME}", reply_markup=_menu_keyboard())
        return

    vault = _load().get(user_id)
    if vault is None:
        PENDING[user_id] = {
            "stage": "create_master", "data": {}, "prompt_id": None, "created": time.time()
        }
        prompt = await message.reply_text(
            "No vault yet. Reply with a new master password to create one "
            f"(min {MIN_MASTER_LENGTH} characters).\n\n"
            "There is NO recovery if you forget it — write it down somewhere safe."
        )
        PENDING[user_id]["prompt_id"] = prompt.message_id
        return

    PENDING[user_id] = {
        "stage": "signin", "data": {}, "prompt_id": None, "created": time.time()
    }
    prompt = await message.reply_text(
        "🔒 Enter your master password to sign in.", reply_markup=_signin_keyboard()
    )
    PENDING[user_id]["prompt_id"] = prompt.message_id


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user_id = str(update.effective_user.id)

    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return

    pending = PENDING.get(user_id)
    if not pending:
        return

    stage = pending["stage"]
    text = message.text or ""

    # Every stage below answers a prompt the bot just asked — delete that
    # prompt and the user's reply immediately (not batched at the end), so
    # the chat never accumulates "What's the purpose?" / "Instagram" pairs.
    prompt_id = pending.get("prompt_id")
    await _delete_message_safe(context, message.chat_id, message.message_id)
    if prompt_id:
        await _delete_message_safe(context, message.chat_id, prompt_id)

    if stage == "create_master":
        if len(text) < MIN_MASTER_LENGTH:
            retry = await message.reply_text(
                f"Too short — master password must be at least {MIN_MASTER_LENGTH} characters. Try again."
            )
            pending["prompt_id"] = retry.message_id
            return

        salt = os.urandom(16)
        key = _derive_key(text, salt)
        vaults = _load()
        vaults[user_id] = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "canary": _make_canary(key),
            "entries": [],
        }
        _save(vaults)
        _set_session(user_id, key)
        PENDING.pop(user_id, None)
        await message.reply_text(
            "✅ Vault created and you're signed in.", reply_markup=_menu_keyboard()
        )
        return

    if stage == "signin":
        vault = _load().get(user_id)

        if not vault:
            PENDING.pop(user_id, None)
            await message.reply_text("No vault found. Send /password_manager to create one.")
            return

        salt = base64.b64decode(vault["salt"])
        key = _derive_key(text, salt)
        if not _verify_canary(key, vault["canary"]):
            retry = await message.reply_text(
                "Wrong master password. Try again, or send /password_manager to restart.",
                reply_markup=_signin_keyboard(),
            )
            pending["prompt_id"] = retry.message_id
            return

        PENDING.pop(user_id, None)
        _set_session(user_id, key)
        await message.reply_text("✅ Signed in.", reply_markup=_menu_keyboard())
        return

    if stage == "add_purpose":
        # Each step counts as activity and refreshes the idle timer — only
        # genuine idle time (not the time spent typing an answer) should
        # sign the user out mid-flow.
        if not _get_valid_session(user_id):
            PENDING.pop(user_id, None)
            await message.reply_text("Your session expired. Sign in again with /password_manager.")
            return
        pending["data"]["purpose"] = text.strip()[:100]
        pending["stage"] = "add_username"
        prompt = await message.reply_text("Username?")
        pending["prompt_id"] = prompt.message_id
        return

    if stage == "add_username":
        if not _get_valid_session(user_id):
            PENDING.pop(user_id, None)
            await message.reply_text("Your session expired. Sign in again with /password_manager.")
            return
        pending["data"]["username"] = text.strip()[:200]
        pending["stage"] = "add_password"
        prompt = await message.reply_text("Password?")
        pending["prompt_id"] = prompt.message_id
        return

    if stage == "add_password":
        pending["data"]["password"] = text.strip()[:500]

        session_key = _get_valid_session(user_id)
        entry_data = dict(pending["data"])
        PENDING.pop(user_id, None)

        if not session_key:
            await message.reply_text("Your session expired. Sign in again with /password_manager.")
            return

        vaults = _load()
        vault = vaults.setdefault(user_id, {"entries": []})
        vault.setdefault("entries", []).append(_encrypt_entry(session_key, entry_data))
        _save(vaults)

        await message.reply_text(
            f"✅ Saved '{entry_data['purpose']}'.", reply_markup=_menu_keyboard()
        )
        return


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return

    user_id = str(update.effective_user.id)
    data = query.data

    if data == "pm:menu":
        if not _get_valid_session(user_id):
            await query.edit_message_text("Your session expired. Send /password_manager to sign in again.")
            return
        await query.edit_message_text(f"{EMOJI} {NAME}", reply_markup=_menu_keyboard())
        return

    if data == "pm:signout":
        SESSIONS.pop(user_id, None)
        await query.edit_message_text("Signed out.")
        return

    if data == "pm:forgotprompt":
        await query.edit_message_text(
            "⚠️ There's no way to recover the old master password — but you "
            "can wipe the old vault (it's already unreadable without it) "
            "and start a fresh one. This permanently deletes every entry in "
            "the old vault. Continue?",
            reply_markup=_forgot_confirm_keyboard(),
        )
        return

    if data == "pm:forgotconfirm":
        vaults = _load()
        vaults.pop(user_id, None)
        _save(vaults)
        SESSIONS.pop(user_id, None)
        PENDING.pop(user_id, None)
        await query.edit_message_text(
            "🗑 Old vault deleted. Send /password_manager to create a new one."
        )
        return

    if data == "pm:forgotcancel":
        await query.edit_message_text(
            "🔒 Enter your master password to sign in.", reply_markup=_signin_keyboard()
        )
        pending = PENDING.get(user_id)
        if pending and pending.get("stage") == "signin":
            pending["prompt_id"] = query.message.message_id
        return

    session_key = _get_valid_session(user_id)
    if not session_key:
        await query.edit_message_text("Your session expired. Send /password_manager to sign in again.")
        return

    if data == "pm:list":
        vault = _load().get(user_id, {"entries": []})
        entries = vault.get("entries", [])
        if not entries:
            await query.edit_message_text("No saved passwords yet.", reply_markup=_menu_keyboard())
            return
        purposes = []
        for token in entries:
            try:
                purposes.append(_decrypt_entry(session_key, token).get("purpose", "(unknown)"))
            except InvalidToken:
                purposes.append("(corrupted entry)")
        await query.edit_message_text("Your saved passwords:", reply_markup=_list_keyboard(purposes))
        return

    if data == "pm:addstart":
        await query.edit_message_text("What's this password for? (e.g. Instagram) Reply with the purpose.")
        PENDING[user_id] = {
            "stage": "add_purpose",
            "data": {},
            "prompt_id": query.message.message_id,
            "created": time.time(),
        }
        return

    if data.startswith("pm:reveal:"):
        idx = int(data.split(":")[2])
        vault = _load().get(user_id, {"entries": []})
        entries = vault.get("entries", [])
        if idx < 0 or idx >= len(entries):
            await query.edit_message_text("That entry no longer exists.", reply_markup=_menu_keyboard())
            return
        try:
            entry = _decrypt_entry(session_key, entries[idx])
        except InvalidToken:
            await query.edit_message_text("Couldn't decrypt that entry.", reply_markup=_menu_keyboard())
            return

        await query.edit_message_text(
            _format_reveal(entry), parse_mode="Markdown", reply_markup=_reveal_keyboard(idx)
        )
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        context.job_queue.run_once(
            _auto_delete_job,
            when=REVEAL_AUTO_DELETE_SECONDS,
            data=(chat_id, message_id),
            name=f"pm_reveal_delete_{chat_id}_{message_id}",
        )
        return

    if data.startswith("pm:del:"):
        idx = int(data.split(":")[2])
        vaults = _load()
        vault = vaults.get(user_id, {"entries": []})
        entries = vault.get("entries", [])
        if 0 <= idx < len(entries):
            entries.pop(idx)
            vault["entries"] = entries
            vaults[user_id] = vault
            _save(vaults)
            await query.edit_message_text("Deleted.", reply_markup=_menu_keyboard())
        else:
            await query.edit_message_text("Already gone.", reply_markup=_menu_keyboard())
        return

    if data == "pm:deleteprompt":
        await query.edit_message_text(
            "⚠️ This permanently deletes your ENTIRE vault — every saved "
            "entry — and cannot be undone. Are you sure?",
            reply_markup=_delete_vault_confirm_keyboard(),
        )
        return

    if data == "pm:deleteconfirm":
        vaults = _load()
        vaults.pop(user_id, None)
        _save(vaults)
        SESSIONS.pop(user_id, None)
        PENDING.pop(user_id, None)
        await query.edit_message_text(
            "🗑 Vault deleted. Send /password_manager to create a new one."
        )
        return


def cleanup() -> int:
    """Purge expired in-memory sessions and abandoned pending flows. Not
    security-critical (expiry is already enforced on access via
    _get_valid_session) — just housekeeping so these dicts don't grow
    unbounded from users who never finish signing in."""
    now = time.time()
    expired_sessions = [uid for uid, s in SESSIONS.items() if now > s["expires"]]
    for uid in expired_sessions:
        SESSIONS.pop(uid, None)

    expired_pending = [uid for uid, p in PENDING.items() if now - p.get("created", now) > PENDING_TTL_SECONDS]
    for uid in expired_pending:
        PENDING.pop(uid, None)

    return len(expired_sessions) + len(expired_pending)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^pm:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & HAS_PENDING, handle_text))
