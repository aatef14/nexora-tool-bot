"""Nexo Meme — classic top-text/bottom-text meme caption generator.

Send a photo with a caption like `top text | bottom text` and get back the
same photo with bold white-with-black-outline classic meme captions burned
into it.
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

NAME = "Nexo Meme"
SLUG = "meme"
COMMAND = "meme"
EMOJI = "😂"
SUMMARY = "Add classic top/bottom meme captions to a photo."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Send me a photo with a caption formatted as:\n"
    "`top text | bottom text`\n\n"
    "Either half can be empty — e.g. `| only bottom text` or "
    "`only top text |`. I'll render both in bold white text with a black "
    "outline, classic meme style, and send the result back."
)

TEMP_PREFIX = "nexora_meme_"

logger = logging.getLogger("nexora-tool-bot.meme")

OUTLINE_OFFSETS = [
    (-2, -2), (-2, 2), (2, -2), (2, 2),
    (0, -2), (0, 2), (-2, 0), (2, 0),
]
PADDING = 12
LINE_SPACING = 6
MAX_WIDTH_RATIO = 0.92


def _wrap_text(draw: "ImageDraw.ImageDraw", text: str, font: "ImageFont.ImageFont", max_width: float) -> list[str]:
    """Greedy word-wrap: keep adding words to a line until it would exceed
    max_width, then start a new line."""
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if width <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_outlined_line(draw: "ImageDraw.ImageDraw", xy: tuple[float, float], line: str, font) -> None:
    x, y = xy
    for dx, dy in OUTLINE_OFFSETS:
        draw.text((x + dx, y + dy), line, font=font, fill="black")
    draw.text((x, y), line, font=font, fill="white")


def render_meme(src_path: str, dst_path: str, top_text: str, bottom_text: str) -> None:
    with Image.open(src_path) as img:
        img = img.convert("RGB")
        width, height = img.size

        font_size = max(24, height // 10)
        font = ImageFont.load_default(size=font_size)

        draw = ImageDraw.Draw(img)
        max_width = width * MAX_WIDTH_RATIO

        def line_height(line: str) -> float:
            bbox = draw.textbbox((0, 0), line or " ", font=font)
            return bbox[3] - bbox[1]

        def centered_x(line: str) -> float:
            bbox = draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            return max(0.0, (width - line_width) / 2)

        if top_text.strip():
            top_lines = _wrap_text(draw, top_text.strip().upper(), font, max_width)
            y = PADDING
            for line in top_lines:
                _draw_outlined_line(draw, (centered_x(line), y), line, font)
                y += line_height(line) + LINE_SPACING

        if bottom_text.strip():
            bottom_lines = _wrap_text(draw, bottom_text.strip().upper(), font, max_width)
            heights = [line_height(line) for line in bottom_lines]
            total_height = sum(heights) + LINE_SPACING * (len(bottom_lines) - 1)
            y = height - PADDING - total_height
            for line, h in zip(bottom_lines, heights):
                _draw_outlined_line(draw, (centered_x(line), y), line, font)
                y += h + LINE_SPACING

        img.save(dst_path, format="JPEG", quality=90)


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

    caption = message.caption or ""
    if "|" in caption:
        top_text, bottom_text = caption.split("|", 1)
    else:
        top_text, bottom_text = caption, ""
    top_text = top_text.strip()
    bottom_text = bottom_text.strip()

    if not top_text and not bottom_text:
        return

    work_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    try:
        file_id = message.photo[-1].file_id
        tg_file = await context.bot.get_file(file_id)
        src_path = os.path.join(work_dir, "src")
        await tg_file.download_to_drive(src_path)

        dst_path = os.path.join(work_dir, "meme.jpg")
        render_meme(src_path, dst_path, top_text, bottom_text)

        with open(dst_path, "rb") as f:
            await message.reply_document(document=f)

    except Exception:
        logger.exception("Meme rendering failed")
        await message.reply_text("Something went wrong making that meme.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
    # Only claim captions containing "|" (the top|bottom separator) — a
    # captioned photo with no pipe belongs to Nexo Watermark instead, and a
    # captionless one belongs to Nexo Image. Keeps all three mutually
    # exclusive at the filter level rather than racing at runtime.
    app.add_handler(MessageHandler(filters.PHOTO & filters.CaptionRegex(r"\|"), handle_photo))
