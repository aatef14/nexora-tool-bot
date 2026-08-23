"""Registry of tool modules the bot loads at startup.

Each tool module exposes:
    NAME, SLUG, EMOJI, SUMMARY   -- metadata used in /start and bot info
    register(app)                -- adds its handlers to the Application
    cleanup() -> int (optional)  -- called by the daily cleanup job

To add a new tool: write tools/<slug>.py following that shape, then add it
to the TOOLS list below.
"""

from . import (
    archive,
    convert,
    expense,
    image,
    link2video,
    meme,
    password,
    password_manager,
    qr,
    reminder,
    weather,
    wiki,
)

TOOLS = [
    # password_manager's text handler only fires for users mid-flow (via a
    # HAS_PENDING filter) but must still be checked before link2video's bare
    # URL-matching handler, in case a pending reply (e.g. a username field)
    # happens to look like a link — first match wins per Telegram update.
    password_manager,
    link2video,
    image,
    meme,
    qr,
    password,
    convert,
    reminder,
    wiki,
    weather,
    archive,
    expense,
]
