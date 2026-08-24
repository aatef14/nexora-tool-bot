#!/data/data/com.termux/files/usr/bin/bash
# Stops the local Bot API server started by local-bot-api-start.sh.
#
# After stopping it, clear LOCAL_BOT_API_URL in .env and restart the bot
# (bot-stop.sh && bot-start.sh) to fall back to Telegram's regular cloud
# API — this is the full rollback if the local server didn't work out.

if pgrep -f "telegram-bot-api" > /dev/null; then
    pkill -f "telegram-bot-api"
    echo "Local Bot API server stopped."
else
    echo "Local Bot API server is not running."
fi
