"""Nexo QR — generate a QR code image from text.

Encoding only. Decoding QR codes from a photo isn't supported yet — that
needs the system zbar library (via pyzbar), which isn't guaranteed to be
installed on every host this bot runs on.
"""

import logging
import os
import shutil
import tempfile

import qrcode
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo QR"
SLUG = "qr"
COMMAND = "qr"
EMOJI = "🔳"
SUMMARY = "Generate a QR code from text or a link."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Send /qr followed by any text or URL and I'll generate a QR code image "
    "for it.\n\n"
    "Example: /qr https://example.com\n\n"
    "Note: decoding QR codes from a photo isn't supported yet — that needs a "
    "system zbar library that isn't guaranteed to be installed on the phone/host."
)

TEMP_PREFIX = "nexora_qr_"
MAX_TEXT_LENGTH = 2000

logger = logging.getLogger("nexora-tool-bot.qr")


def generate_qr_png(text: str, out_path: str) -> None:
    """Encode text as a QR code and save it as a PNG at out_path."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(out_path)


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    if not is_allowed(update.effective_user.id):
        await message.reply_text(PRIVATE_MESSAGE)
        return

    if not context.args:
        await message.reply_text(USAGE)
        return

    text = " ".join(context.args)
    if len(text) > MAX_TEXT_LENGTH:
        await message.reply_text(
            f"That's too long ({len(text)} chars). Please keep it under {MAX_TEXT_LENGTH} characters."
        )
        return

    work_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    try:
        out_path = os.path.join(work_dir, "qr.png")
        generate_qr_png(text, out_path)

        caption = text if len(text) <= 200 else text[:200] + "..."

        with open(out_path, "rb") as f:
            await message.reply_photo(photo=f, caption=f"Encoded: {caption}")

    except Exception:
        logger.exception("Failed to generate QR code")
        await message.reply_text("Something went wrong generating that QR code.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
