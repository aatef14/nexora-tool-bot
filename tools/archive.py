"""Nexo Archive — unzip a .zip file sent to the bot.

v1 is extract-only and zip-only: no rarfile/py7zr/7z support (those need
extra system binaries that aren't guaranteed to exist on the phone running
this bot), and creating new zip files isn't supported yet either.
"""

import logging
import os
import shutil
import tempfile
import time
import zipfile

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.access import deny_access, is_allowed

NAME = "Nexo Archive"
SLUG = "archive"
COMMAND = "archive"
EMOJI = "📦"
SUMMARY = "Unzip a .zip file sent to the bot."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Send me a .zip file as a document and I'll extract it, sending each "
    "contained file back individually.\n\n"
    "Limits:\n"
    "- Up to 20 files per archive (to avoid spamming the chat).\n"
    f"- Each extracted file must be under {os.environ.get('MAX_FILE_SIZE_MB', '50')}MB "
    "(same limit as the rest of the bot).\n\n"
    "Note: this only extracts .zip files (v1 is zip-only, no .rar/.7z). "
    "Creating new zip files isn't supported yet either."
)

TEMP_PREFIX = "nexora_archive_"
STALE_TEMP_DIR_AGE_SECONDS = 60 * 60
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "50"))
MAX_FILES_PER_ARCHIVE = 20

logger = logging.getLogger("nexora-tool-bot.archive")


def is_safe_member_path(member_name: str, dest_dir: str) -> str | None:
    """Resolve a zip member's intended output path under dest_dir and return
    it only if it actually stays inside dest_dir (guards against zip-slip
    path traversal via '..' segments, absolute paths, drive letters, etc.).
    Returns None if the member is unsafe."""
    dest_abs = os.path.abspath(dest_dir)
    target_path = os.path.abspath(os.path.join(dest_dir, member_name))
    if target_path != dest_abs and not target_path.startswith(dest_abs + os.sep):
        return None
    return target_path


def safe_extract(
    zf: zipfile.ZipFile, dest_dir: str, max_files: int, max_file_size: int
) -> tuple[list[str], list[str]]:
    """Extract up to max_files non-directory members of zf into dest_dir,
    skipping unsafe paths (zip-slip) and files over max_file_size.

    Returns (extracted_paths, skipped_reasons)."""
    extracted: list[str] = []
    skipped: list[str] = []

    members = [m for m in zf.infolist() if not m.is_dir()]
    total = len(members)
    truncated = total > max_files
    members = members[:max_files]

    for member in members:
        target_path = is_safe_member_path(member.filename, dest_dir)
        if target_path is None:
            skipped.append(f"{member.filename} (unsafe path, skipped)")
            continue

        if member.file_size > max_file_size:
            skipped.append(f"{member.filename} (too large, skipped)")
            continue

        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with zf.open(member) as src, open(target_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

        actual_size = os.path.getsize(target_path)
        if actual_size > max_file_size:
            os.remove(target_path)
            skipped.append(f"{member.filename} (too large, skipped)")
            continue

        extracted.append(target_path)

    if truncated:
        skipped.append(f"archive had {total} files, only the first {max_files} were processed")

    return extracted, skipped


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return
    await update.effective_message.reply_text(USAGE)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    if not is_allowed(update.effective_user.id):
        await deny_access(update)
        return

    document = message.document
    if not document:
        return

    work_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    zip_path = os.path.join(work_dir, "archive.zip")
    extract_dir = os.path.join(work_dir, "extracted")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        tg_file = await context.bot.get_file(document.file_id)
        await tg_file.download_to_drive(zip_path)

        try:
            with zipfile.ZipFile(zip_path) as zf:
                member_count = sum(1 for m in zf.infolist() if not m.is_dir())
                status = await message.reply_text(
                    f"Extracting {min(member_count, MAX_FILES_PER_ARCHIVE)} file(s)..."
                )
                extracted, skipped = safe_extract(
                    zf, extract_dir, MAX_FILES_PER_ARCHIVE, MAX_FILE_SIZE_MB * 1024 * 1024
                )
        except zipfile.BadZipFile:
            await message.reply_text("That doesn't look like a valid zip file.")
            return

        for path in extracted:
            try:
                with open(path, "rb") as f:
                    await message.reply_document(document=f, filename=os.path.basename(path))
            except Exception:
                logger.exception("Failed to send extracted file %s", path)
                skipped.append(f"{os.path.basename(path)} (failed to send)")

        await status.delete()

        if skipped:
            summary = "Some files were skipped:\n" + "\n".join(f"- {s}" for s in skipped)
            await message.reply_text(summary)
        elif not extracted:
            await message.reply_text("The archive didn't contain any files to extract.")

    except Exception:
        logger.exception("Unexpected error handling archive")
        await message.reply_text("Something went wrong processing that archive.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def cleanup() -> int:
    """Remove leftover temp dirs (normally cleaned up per-archive, but a
    crash mid-extraction can strand one). Returns count of temp dirs removed."""
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
    return removed


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
    app.add_handler(MessageHandler(filters.Document.ZIP, handle_document))
    cleanup()
