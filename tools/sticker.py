"""Nexo Sticker — turn a photo into a Telegram sticker-format image.

Telegram's `send_sticker` / `reply_sticker` accepts a static WEBP (or PNG) up
to 512x512 as a one-off sticker message — it does NOT need to be added to a
sticker pack/set first. We still save as WEBP specifically (not just a
renamed PNG) since that's the documented native static-sticker format and
some Bot API paths are stricter about accepting PNG outside of a sticker set.
"""

import logging
import os
import shutil
import tempfile

from PIL import Image
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Sticker"
SLUG = "sticker"
COMMAND = "sticker"
EMOJI = "🏷️"
SUMMARY = "Turn a photo into a Telegram sticker."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Reply to a photo with /sticker and I'll convert it into a Telegram "
    "sticker (resized so one side is 512px) and send it back.\n\n"
    "Just sending /sticker on its own shows this message."
)

TEMP_PREFIX = "nexora_sticker_"

logger = logging.getLogger("nexora-tool-bot.sticker")


def make_sticker(src_path: str, dst_path: str) -> None:
    """Resize the image so one side is exactly 512px (the other <=512px,
    aspect ratio preserved) and save it as a static WEBP, per Telegram's
    sticker image requirements."""
    with Image.open(src_path) as img:
        img = img.convert("RGBA")
        width, height = img.size

        if width >= height:
            new_width = 512
            new_height = round(height * 512 / width)
        else:
            new_height = 512
            new_width = round(width * 512 / height)

        resized = img.resize((new_width, new_height), Image.LANCZOS)
        resized.save(dst_path, format="WEBP")


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /sticker. Only converts when sent as a reply to a photo
    message — there's no reliable way to disambiguate a bare photo send
    from image.py's own bare-photo handler, so we require the explicit
    reply-to-photo gesture instead of registering a competing PHOTO handler."""
    message = update.effective_message

    if not is_allowed(update.effective_user.id):
        await message.reply_text(PRIVATE_MESSAGE)
        return

    reply_to = message.reply_to_message
    if not reply_to or not reply_to.photo:
        await message.reply_text(
            "Reply to a photo with /sticker to convert it.\n\n" + USAGE
        )
        return

    file_id = reply_to.photo[-1].file_id  # largest size Telegram generated

    work_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    try:
        src_path = os.path.join(work_dir, "src")
        dst_path = os.path.join(work_dir, "result.webp")

        tg_file = await context.bot.get_file(file_id)
        await tg_file.download_to_drive(src_path)

        make_sticker(src_path, dst_path)

        with open(dst_path, "rb") as f:
            await message.reply_sticker(sticker=f)

    except Exception:
        logger.exception("Sticker conversion failed")
        await message.reply_text("Something went wrong turning that photo into a sticker.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
