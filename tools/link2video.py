"""Nexo Link2video — download a video/audio link as MP4 or MP3.

Supports anything yt-dlp supports (YouTube, YouTube Shorts, Instagram,
TikTok, X/Twitter, Facebook, Reddit, and 1000+ other sites); we just try to
recognize the domain for a friendly label and let yt-dlp fail gracefully on
anything it can't actually handle.
"""

import logging
import os
import re
import shutil
import tempfile
import time
import uuid

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Link2video"
SLUG = "link2video"
COMMAND = "link2video"
EMOJI = "🎬"
SUMMARY = "Send a video link (YouTube, TikTok, Instagram, X, Facebook, Reddit...) and get it back as MP4 or MP3."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Send me a video link from YouTube, YouTube Shorts, Instagram, TikTok, "
    "X/Twitter, Facebook, or Reddit. I'll ask whether you want MP4 or MP3 "
    "and what quality, then send the file back.\n\n"
    f"Max file size: {os.environ.get('MAX_FILE_SIZE_MB', '50')}MB (Telegram Bot API limit)."
)

INSTAGRAM_COOKIES_FILE = os.environ.get("INSTAGRAM_COOKIES_FILE") or None
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "50"))

TEMP_PREFIX = "nexora_link2video_"
STALE_TEMP_DIR_AGE_SECONDS = 60 * 60
PENDING_URL_MAX_AGE_SECONDS = 30 * 60

PLATFORM_LABELS = [
    (re.compile(r"(youtube\.com/shorts/)", re.IGNORECASE), "YouTube Shorts"),
    (re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE), "YouTube"),
    (re.compile(r"instagram\.com/reel", re.IGNORECASE), "Instagram Reel"),
    (re.compile(r"instagram\.com", re.IGNORECASE), "Instagram"),
    (re.compile(r"tiktok\.com", re.IGNORECASE), "TikTok"),
    (re.compile(r"(twitter\.com|x\.com)", re.IGNORECASE), "X / Twitter"),
    (re.compile(r"facebook\.com|fb\.watch", re.IGNORECASE), "Facebook"),
    (re.compile(r"reddit\.com", re.IGNORECASE), "Reddit"),
]

URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)

VIDEO_QUALITIES = [
    ("best", "Best available"),
    ("1080", "1080p"),
    ("720", "720p"),
    ("480", "480p"),
    ("360", "360p"),
]
AUDIO_QUALITIES = [
    ("320", "320 kbps"),
    ("192", "192 kbps"),
    ("128", "128 kbps"),
]

# Telegram callback_data is capped at 64 bytes, too short for most URLs, so
# button presses carry a short id that looks the URL up here instead.
# Each value is (url, created_at) so stale entries can be swept.
PENDING_URLS: dict[str, tuple[str, float]] = {}

logger = logging.getLogger("nexora-tool-bot.link2video")


def detect_platform(url: str) -> str:
    for pattern, label in PLATFORM_LABELS:
        if pattern.search(url):
            return label
    return "link"


def remember_url(url: str) -> str:
    req_id = uuid.uuid4().hex[:12]
    PENDING_URLS[req_id] = (url, time.time())
    return req_id


def format_keyboard(req_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎬 MP4 (video)", callback_data=f"l2v:fmt:{req_id}:mp4"),
                InlineKeyboardButton("🎵 MP3 (audio)", callback_data=f"l2v:fmt:{req_id}:mp3"),
            ]
        ]
    )


def quality_keyboard(req_id: str, fmt: str) -> InlineKeyboardMarkup:
    options = VIDEO_QUALITIES if fmt == "mp4" else AUDIO_QUALITIES
    row = [
        InlineKeyboardButton(label, callback_data=f"l2v:dl:{req_id}:{fmt}:{value}")
        for value, label in options
    ]
    # Two buttons per row so it fits on a phone screen.
    rows = [row[i : i + 2] for i in range(0, len(row), 2)]
    return InlineKeyboardMarkup(rows)


def build_ydl_opts(out_path: str, url: str, fmt: str, quality: str) -> dict:
    opts = {
        "outtmpl": out_path,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_FILE_SIZE_MB * 1024 * 1024,
    }

    if fmt == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }
        ]
    else:
        height_filter = f"[height<={quality}]" if quality != "best" else ""
        opts["format"] = (
            f"bestvideo{height_filter}[ext=mp4]+bestaudio[ext=m4a]"
            f"/best{height_filter}[ext=mp4]/best{height_filter}/best"
        )
        opts["merge_output_format"] = "mp4"

    if "instagram.com" in url and INSTAGRAM_COOKIES_FILE:
        opts["cookiefile"] = INSTAGRAM_COOKIES_FILE
    return opts


def format_duration(seconds) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def find_output_file(work_dir: str) -> str | None:
    """yt-dlp's postprocessors (e.g. mp3 extraction) can change the final
    extension, so instead of guessing the path we just find the one real
    output file it left behind."""
    candidates = [
        f
        for f in os.listdir(work_dir)
        if not f.endswith((".part", ".ytdl", ".description", ".json"))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda f: os.path.getsize(os.path.join(work_dir, f)), reverse=True)
    return os.path.join(work_dir, candidates[0])


async def process_download(url: str, fmt: str, quality: str, status, reply_target) -> None:
    """Download url as fmt/quality, editing status messages along the way,
    and send the result via reply_target.reply_video/reply_audio."""
    platform = detect_platform(url)
    await status.edit_text(f"Detected: {platform}\nDownloading...")

    work_dir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
    out_template = os.path.join(work_dir, f"{uuid.uuid4().hex}.%(ext)s")

    try:
        ydl_opts = build_ydl_opts(out_template, url, fmt, quality)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        file_path = find_output_file(work_dir)
        if not file_path:
            await status.edit_text("Download failed: no output file produced.")
            return

        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            await status.edit_text(
                f"File is {size_mb:.1f}MB, over the {MAX_FILE_SIZE_MB}MB Telegram limit. "
                "Try a lower quality, or run a local Bot API server to raise this to 2GB."
            )
            return

        title = info.get("title") or ""
        duration = format_duration(info.get("duration"))
        uploader = info.get("uploader") or ""
        caption_parts = [p for p in [title, uploader, duration] if p]
        caption = "\n".join(caption_parts)[:1024] or None

        await status.edit_text(f"Detected: {platform}\nUploading...")
        with open(file_path, "rb") as f:
            if fmt == "mp3":
                await reply_target.reply_audio(audio=f, caption=caption, title=title or None)
            else:
                await reply_target.reply_video(video=f, caption=caption, supports_streaming=True)
        await status.delete()

    except yt_dlp.utils.DownloadError as e:
        logger.warning("Download error for %s: %s", url, e)
        await status.edit_text(f"Couldn't download that link: {e}")
    except Exception:
        logger.exception("Unexpected error handling %s", url)
        await status.edit_text("Something went wrong processing that link.")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /link2video — shows usage instructions. The tool itself
    activates as soon as a message contains a link, no arguments needed."""
    if not is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(PRIVATE_MESSAGE)
        return
    await update.effective_message.reply_text(USAGE)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    if not is_allowed(update.effective_user.id):
        await message.reply_text(PRIVATE_MESSAGE)
        return

    text = message.text or ""
    match = URL_RE.search(text)
    if not match:
        return

    url = match.group(0)
    req_id = remember_url(url)
    platform = detect_platform(url)
    await message.reply_text(
        f"Detected: {platform}\nChoose a format:",
        reply_markup=format_keyboard(req_id),
    )


async def handle_format_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_allowed(update.effective_user.id):
        await query.edit_message_text(PRIVATE_MESSAGE)
        return

    _, _, req_id, fmt = query.data.split(":")
    entry = PENDING_URLS.get(req_id)
    if not entry:
        await query.edit_message_text("This link expired, please send it again.")
        return

    await query.edit_message_text("Choose a quality:", reply_markup=quality_keyboard(req_id, fmt))


async def handle_quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_allowed(update.effective_user.id):
        await query.edit_message_text(PRIVATE_MESSAGE)
        return

    _, _, req_id, fmt, quality = query.data.split(":")
    entry = PENDING_URLS.pop(req_id, None)
    if not entry:
        await query.edit_message_text("This link expired, please send it again.")
        return

    url, _ = entry
    status = query.message
    await process_download(url, fmt, quality, status, status)


def cleanup() -> int:
    """Remove leftover temp dirs (normally cleaned up per-download, but a
    crash mid-download can strand one) and expire stale pending URLs.
    Returns count of temp dirs removed."""
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

    stale = [rid for rid, (_, created) in PENDING_URLS.items() if now - created > PENDING_URL_MAX_AGE_SECONDS]
    for rid in stale:
        PENDING_URLS.pop(rid, None)

    return removed


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
    app.add_handler(CallbackQueryHandler(handle_format_choice, pattern=r"^l2v:fmt:"))
    app.add_handler(CallbackQueryHandler(handle_quality_choice, pattern=r"^l2v:dl:"))
    app.add_handler(MessageHandler(filters.Regex(URL_RE) & ~filters.COMMAND, handle_message))
    cleanup()
