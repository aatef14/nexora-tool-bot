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
    crypto,
    expense,
    image,
    link2video,
    meme,
    notes,
    password,
    poll,
    qr,
    reminder,
    sticker,
    watermark,
    weather,
    wiki,
)

TOOLS = [
    link2video,
    image,
    watermark,
    meme,
    sticker,
    qr,
    password,
    convert,
    notes,
    reminder,
    poll,
    wiki,
    weather,
    crypto,
    archive,
    expense,
]
