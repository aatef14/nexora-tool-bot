"""Nexo Image — compress, resize, convert, or strip EXIF from a photo.

Send any photo (as a photo or as a file, to preserve full quality) and pick
what to do with it from the buttons; the result comes back as a document so
Telegram doesn't re-compress it a second time on the way out.
"""

import logging
import os
import shutil
import tempfile
import time
import uuid

from PIL import Image, ImageOps
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

NAME = "Nexo Image"
SLUG = "image"
COMMAND = "image"
EMOJI = "🖼️"
SUMMARY = "Send a photo to compress, resize, convert, or strip EXIF data from it."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Send me a photo (as a photo, or as a file to keep full quality) and "
    "I'll ask what to do with it:\n"
    "🗜 Compress — shrink the file size\n"
    "📐 Resize — scale it down\n"
    "🔁 Convert — change format (JPEG/PNG/WEBP/BMP)\n"
    "🧹 Strip EXIF — remove location/camera metadata\n\n"
    "The result comes back as a file so Telegram doesn't re-compress it again."
)

TEMP_PREFIX = "nexora_image_"
STALE_TEMP_DIR_AGE_SECONDS = 60 * 60
PENDING_MAX_AGE_SECONDS = 30 * 60

COMPRESS_LEVELS = [
    ("85", "🟢 Light"),
    ("65", "🟡 Medium"),
    ("40", "🔴 Heavy"),
]
RESIZE_LEVELS = [
    ("75", "75%"),
    ("50", "50%"),
    ("25", "25%"),
]
CONVERT_FORMATS = [
    ("JPEG", "JPEG"),
    ("PNG", "PNG"),
    ("WEBP", "WEBP"),
    ("BMP", "BMP"),
]

# Same reasoning as Nexo Link2video: callback_data is capped at 64 bytes, so
# button presses carry a short id that looks the file_id up here instead.
PENDING_IMAGES: dict[str, tuple[str, float]] = {}

logger = logging.getLogger("nexora-tool-bot.image")


def remember_file(file_id: str) -> str:
    req_id = uuid.uuid4().hex[:12]
    PENDING_IMAGES[req_id] = (file_id, time.time())
    return req_id


def action_keyboard(req_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🗜 Compress", callback_data=f"img:act:{req_id}:compress"),
                InlineKeyboardButton("📐 Resize", callback_data=f"img:act:{req_id}:resize"),
            ],
            [
                InlineKeyboardButton("🔁 Convert", callback_data=f"img:act:{req_id}:convert"),
                InlineKeyboardButton("🧹 Strip EXIF", callback_data=f"img:act:{req_id}:exif"),
            ],
        ]
    )


def option_keyboard(req_id: str, action: str) -> InlineKeyboardMarkup:
    options = {"compress": COMPRESS_LEVELS, "resize": RESIZE_LEVELS, "convert": CONVERT_FORMATS}[action]
    row = [
        InlineKeyboardButton(label, callback_data=f"img:run:{req_id}:{action}:{value}")
        for value, label in options
    ]
    rows = [row[i : i + 2] for i in range(0, len(row), 2)]
    return InlineKeyboardMarkup(rows)


def human_size(num_bytes: int) -> str:
    size_kb = num_bytes / 1024
    if size_kb < 1024:
        return f"{size_kb:.0f}KB"
    return f"{size_kb / 1024:.1f}MB"


def apply_operation(src_path: str, dst_path: str, action: str, value: str) -> None:
    with Image.open(src_path) as img:
        img = ImageOps.exif_transpose(img)  # bake in rotation before dropping EXIF

        if action == "compress":
            rgb = img.convert("RGB")
            rgb.save(dst_path, format="JPEG", quality=int(value), optimize=True)
            return

        if action == "resize":
            pct = int(value) / 100
            new_size = (max(1, int(img.width * pct)), max(1, int(img.height * pct)))
            resized = img.resize(new_size, Image.LANCZOS)
            resized.save(dst_path, format=img.format or "PNG")
            return

        if action == "convert":
            target = value
            out_img = img.convert("RGB") if target in ("JPEG", "BMP") else img
            out_img.save(dst_path, format=target)
            return

        if action == "exif":
            # exif_transpose above already dropped orientation into pixels;
            # re-saving without exif= drops the rest of the metadata too.
            img.save(dst_path, format=img.format or "PNG")
            return

        raise ValueError(f"Unknown action: {action}")


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return
    await update.effective_message.reply_text(USAGE)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return

    if message.photo:
        file_id = message.photo[-1].file_id  # largest size Telegram generated
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id
    else:
        return

    req_id = remember_file(file_id)
    await message.reply_text("What would you like to do with it?", reply_markup=action_keyboard(req_id))


async def handle_action_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return

    _, _, req_id, action = query.data.split(":")
    if req_id not in PENDING_IMAGES:
        await query.edit_message_text("This photo expired, please send it again.")
        return

    if action == "exif":
        await run_operation(req_id, action, "0", query.message, query.message)
        return

    prompts = {
        "compress": "Choose how much to compress:",
        "resize": "Choose a scale:",
        "convert": "Choose a target format:",
    }
    await query.edit_message_text(prompts[action], reply_markup=option_keyboard(req_id, action))


async def handle_run_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return

    _, _, req_id, action, value = query.data.split(":")
    await run_operation(req_id, action, value, query.message, query.message)


async def run_operation(req_id: str, action: str, value: str, status, reply_target) -> None:
    entry = PENDING_IMAGES.pop(req_id, None)
    if not entry:
        await status.edit_text("This photo expired, please send it again.")
        return
    file_id, _ = entry

    await status.edit_text("Processing...")
    work_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)

    try:
        tg_file = await status.get_bot().get_file(file_id)
        src_path = os.path.join(work_dir, "src")
        await tg_file.download_to_drive(src_path)
        original_size = os.path.getsize(src_path)

        if action in ("compress", "convert"):
            ext = "jpg" if action == "compress" else value.lower()
        else:
            # resize/exif keep the original format, so name the file to match
            with Image.open(src_path) as probe:
                ext = (probe.format or "png").lower()
        dst_path = os.path.join(work_dir, f"result.{ext}")
        apply_operation(src_path, dst_path, action, value)

        result_size = os.path.getsize(dst_path)
        caption = f"{human_size(original_size)} → {human_size(result_size)}"

        with open(dst_path, "rb") as f:
            await reply_target.reply_document(document=f, caption=caption)
        await status.delete()

    except Exception:
        logger.exception("Image operation failed (action=%s)", action)
        await status.edit_text("Something went wrong processing that image.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def cleanup() -> int:
    removed = 0
    tmp_root = tempfile.gettempdir()
    now = time.time()
    try:
        entries = os.listdir(tmp_root)
    except OSError:
        entries = []
    for name in entries:
        if not name.startswith(TEMP_PREFIX):
            continue
        path = os.path.join(tmp_root, name)
        try:
            if now - os.path.getmtime(path) < STALE_TEMP_DIR_AGE_SECONDS:
                continue
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
        except OSError:
            pass

    stale = [rid for rid, (_, created) in PENDING_IMAGES.items() if now - created > PENDING_MAX_AGE_SECONDS]
    for rid in stale:
        PENDING_IMAGES.pop(rid, None)

    return removed


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
    app.add_handler(CallbackQueryHandler(handle_action_choice, pattern=r"^img:act:"))
    app.add_handler(CallbackQueryHandler(handle_run_choice, pattern=r"^img:run:"))
    # Nexo Meme claims any caption containing "|" — everything else
    # (captionless, or captioned without a pipe) is ours, so the two tools
    # don't race for the same photo message.
    app.add_handler(
        MessageHandler(
            (filters.PHOTO & ~filters.CaptionRegex(r"\|")) | filters.Document.IMAGE, handle_photo
        )
    )
    cleanup()
