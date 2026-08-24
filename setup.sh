#!/data/data/com.termux/files/usr/bin/bash
# One-shot Termux setup for Nexora Tool Bot.
# Run this inside Termux after installing Termux, Termux:Boot, and Termux:API from F-Droid.

set -e

echo "==> Updating Termux packages"
pkg update -y && pkg upgrade -y

echo "==> Installing Python, Node, ffmpeg, git"
pkg install -y python nodejs ffmpeg git

echo "==> Installing prebuilt python-cryptography (needed by Nexo Password Manager)"
# pip can't build the `cryptography` package's Rust extension on Termux —
# rustup (which it tries to auto-fetch) doesn't support Android's target
# triple at all. Termux ships a prebuilt wheel for this exact reason.
pkg install -y python-cryptography

echo "==> Enabling storage access (approve the Android permission prompt)"
termux-setup-storage

echo "==> Installing Python dependencies"
pip install -r requirements.txt

echo "==> Making scripts executable"
chmod +x bot-start.sh bot-stop.sh bot-logs.sh bot-debug.sh web-start.sh web-stop.sh

echo "==> Setting up boot autostart"
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/start-bot.sh <<EOF
#!/data/data/com.termux/files/usr/bin/bash
bash "$(pwd)/bot-start.sh"
EOF
chmod +x ~/.termux/boot/start-bot.sh

echo "==> Acquiring wake lock for this session"
termux-wake-lock

echo ""
echo "Setup complete."
echo "1. Copy .env.example to .env and add your BOT_TOKEN."
echo "2. Start the bot with:   bash bot-start.sh"
echo "3. Watch live logs with: bash bot-logs.sh"
echo "4. Stop the bot with:    bash bot-stop.sh"
echo "5. It will also auto-start on phone reboot via Termux:Boot."
