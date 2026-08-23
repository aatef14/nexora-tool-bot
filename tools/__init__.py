"""Registry of tool modules the bot loads at startup.

Each tool module exposes:
    NAME, SLUG, EMOJI, SUMMARY   -- metadata used in /start and bot info
    register(app)                -- adds its handlers to the Application
    cleanup() -> int (optional)  -- called by the daily cleanup job

To add a new tool: write tools/<slug>.py following that shape, then add it
to the TOOLS list below.
"""

from . import link2video

TOOLS = [
    link2video,
]
