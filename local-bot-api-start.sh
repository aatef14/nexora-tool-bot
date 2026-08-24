#!/data/data/com.termux/files/usr/bin/bash
# Starts a self-hosted local Bot API server in the background. This raises
# the file-size limit from Telegram's standard 50MB up to 2GB.
#
# Requires:
#   1. A compiled/installed `telegram-bot-api` binary on PATH — see
#      "Optional: local Bot API server" in README.md for how to get one.
#   2. TELEGRAM_API_ID and TELEGRAM_API_HASH set in .env (from
#      https://my.telegram.org).
# After this is running, set LOCAL_BOT_API_URL=http://127.0.0.1:8081 in
# .env and restart the bot (bot-stop.sh && bot-start.sh) to use it.

cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "No .env file found. Run: cp .env.example .env, then edit it first."
    exit 1
fi

TELEGRAM_API_ID=$(grep -E '^TELEGRAM_API_ID=' .env 2>/dev/null | cut -d= -f2-)
TELEGRAM_API_HASH=$(grep -E '^TELEGRAM_API_HASH=' .env 2>/dev/null | cut -d= -f2-)

if [ -z "$TELEGRAM_API_ID" ] || [ -z "$TELEGRAM_API_HASH" ]; then
    echo "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env."
    echo "Get them from https://my.telegram.org (Api development tools)."
    exit 1
fi

if ! command -v telegram-bot-api > /dev/null; then
    echo "telegram-bot-api binary not found on PATH."
    echo "See 'Optional: local Bot API server' in README.md to install/build it."
    exit 1
fi

if pgrep -f "telegram-bot-api" > /dev/null; then
    echo "Local Bot API server is already running. Use 'bash local-bot-api-stop.sh' first if you want to restart it."
    exit 1
fi

mkdir -p telegram-bot-api-data

nohup telegram-bot-api \
    --api-id="$TELEGRAM_API_ID" \
    --api-hash="$TELEGRAM_API_HASH" \
    --http-port=8081 \
    --dir=telegram-bot-api-data \
    >> local-bot-api.log 2>&1 &
disown

sleep 3

if pgrep -f "telegram-bot-api" > /dev/null; then
    echo "Local Bot API server started on http://127.0.0.1:8081."
    echo "Now set LOCAL_BOT_API_URL=http://127.0.0.1:8081 in .env, then:"
    echo "  bash bot-stop.sh && bash bot-start.sh"
    echo "Stop the server with: bash local-bot-api-stop.sh"
else
    echo "Failed to start. Last log lines:"
    echo "---"
    tail -n 20 local-bot-api.log
    exit 1
fi
