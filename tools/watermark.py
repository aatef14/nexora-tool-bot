"""Nexo Watermark — stamp text onto a photo.

Send a photo WITH the watermark text as its caption; the bot stamps the text
near the bottom-right corner and sends the result back as a document (so
Telegram doesn't re-compress it).
"""

import logging
import os
import shutil
import tempfile

from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Watermark"
SLUG = "watermark"
COMMAND = "watermark"
EMOJI = "💧"
SUMMARY = "Stamp text onto a photo as a watermark."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Send me a photo WITH the watermark text as its caption, and I'll stamp "
    "it onto the photo (near the bottom-right corner) and send it back.\n\n"
    "If you send a photo without a caption, I'll ask you to resend it with "
    "the text as the caption."
)

TEMP_PREFIX = "nexora_watermark_"
MAX_WATERMARK_CHARS = 60

logger = logging.getLogger("nexora-tool-bot.watermark")


def apply_watermark(src_path: str, dst_path: str, text: str) -> None:
    """Stamp text near the bottom-right corner of the image and save as PNG,
    preserving the original resolution."""
    text = (text or "").strip()
    if len(text) > MAX_WATERMARK_CHARS:
        text = text[:MAX_WATERMARK_CHARS]

    with Image.open(src_path) as img:
        img = img.convert("RGBA")
        width, height = img.size

        font_size = max(18, width // 25)
        font = ImageFont.load_default(size=font_size)

        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        padding = 10
        x = width - text_width - padding - bbox[0]
        y = height - text_height - padding - bbox[1]

        # Cheap outline effect: black offset in 4 directions, then white on top,
        # so the text stays legible on both light and dark backgrounds.
        outline_color = (0, 0, 0, 255)
        fill_color = (255, 255, 255, 255)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
        draw.text((x, y), text, font=font, fill=fill_color)

        img.save(dst_path, format="PNG")


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(PRIVATE_MESSAGE)
        return
    await update.effective_message.reply_text(USAGE)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    if not is_allowed(update.effective_user.id):
        await message.reply_text(PRIVATE_MESSAGE)
        return

    caption = (message.caption or "").strip()
    if not caption:
        await message.reply_text("Send the photo again with your watermark text as the caption.")
        return

    work_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    try:
        file_id = message.photo[-1].file_id
        tg_file = await message.get_bot().get_file(file_id)
        src_path = os.path.join(work_dir, "src")
        await tg_file.download_to_drive(src_path)

        dst_path = os.path.join(work_dir, "result.png")
        apply_watermark(src_path, dst_path, caption)

        with open(dst_path, "rb") as f:
            await message.reply_document(document=f, caption="Watermarked.")

    except Exception:
        logger.exception("Watermark operation failed")
        await message.reply_text("Something went wrong watermarking that photo.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
    # Nexo Image only handles captionless photos, and Nexo Meme claims any
    # caption containing "|" — so this tool takes captioned photos WITHOUT
    # a pipe, keeping all three mutually exclusive at the filter level.
    app.add_handler(
        MessageHandler(filters.PHOTO & filters.CAPTION & ~filters.CaptionRegex(r"\|"), handle_photo)
    )
