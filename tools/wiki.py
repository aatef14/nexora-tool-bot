"""Nexo Wiki — quick Wikipedia summary lookup, no API key needed."""

import asyncio
import logging
import urllib.parse

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.access import PRIVATE_MESSAGE, is_allowed

NAME = "Nexo Wiki"
SLUG = "wiki"
COMMAND = "wiki"
EMOJI = "📖"
SUMMARY = "Look up a quick Wikipedia summary for a topic."
USAGE = (
    f"{EMOJI} {NAME}\n\n"
    "Send /wiki followed by a topic and I'll fetch a quick summary from "
    "Wikipedia.\n\n"
    "Example: /wiki Python (programming language)"
)

WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{}"
REQUEST_HEADERS = {"User-Agent": "NexoraToolBot/1.0 (Telegram bot)"}
REQUEST_TIMEOUT_SECONDS = 8
EXTRACT_MAX_CHARS = 800

logger = logging.getLogger("nexora-tool-bot.wiki")


async def fetch_summary(topic: str) -> dict | None:
    """Fetch a Wikipedia page summary for topic.

    Returns a dict with keys "title", "extract", and optionally "url", or
    None if no matching article exists. Raises RuntimeError on any other
    failure (network error, timeout, unexpected status, malformed JSON).
    """
    encoded_topic = urllib.parse.quote(topic)
    url = WIKI_SUMMARY_URL.format(encoded_topic)

    try:
        response = await asyncio.to_thread(
            requests.get,
            url,
            headers=REQUEST_HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Wikipedia request failed: {e}") from e

    if response.status_code == 404:
        return None

    if response.status_code != 200:
        raise RuntimeError(f"Wikipedia returned status {response.status_code}")

    try:
        data = response.json()
    except ValueError as e:
        raise RuntimeError(f"Wikipedia returned malformed JSON: {e}") from e

    try:
        result = {
            "title": data["title"],
            "extract": data["extract"],
        }
    except (KeyError, TypeError) as e:
        raise RuntimeError(f"Wikipedia response missing expected fields: {e}") from e

    page_url = data.get("content_urls", {}).get("desktop", {}).get("page")
    if page_url:
        result["url"] = page_url

    return result


async def command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.effective_message.reply_text(PRIVATE_MESSAGE)
        return

    if not context.args:
        await update.effective_message.reply_text(USAGE)
        return

    topic = " ".join(context.args)

    try:
        result = await fetch_summary(topic)
    except RuntimeError as e:
        logger.warning("Failed to fetch wikipedia summary for %r: %s", topic, e)
        await update.effective_message.reply_text(
            "Couldn't reach Wikipedia right now, try again later."
        )
        return

    if result is None:
        await update.effective_message.reply_text(
            f"No Wikipedia article found for '{topic}'."
        )
        return

    extract = result["extract"]
    if len(extract) > EXTRACT_MAX_CHARS:
        extract = extract[:EXTRACT_MAX_CHARS] + "..."

    lines = [result["title"], "", extract]
    if result.get("url"):
        lines.append("")
        lines.append(result["url"])

    await update.effective_message.reply_text("\n".join(lines))


def register(app: Application) -> None:
    app.add_handler(CommandHandler(COMMAND, command))
