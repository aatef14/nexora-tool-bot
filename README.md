# Nexora Tool Bot

A Telegram bot that bundles a growing collection of self-hosted utility
tools behind one bot. It runs on your own Android phone via Termux — no
rented server needed.

**Available tools:**

| Tool | Command | What it does |
|---|---|---|
| 🔑 **Nexo Password Manager** | `/password_manager` | An encrypted vault of saved logins — create/sign in, list, reveal, add. |
| 🎬 **Nexo Link2video** | `/link2video` | Send a video link (YouTube, TikTok, Instagram, X, Facebook, Reddit...) and get it back as MP4 or MP3. |
| 🖼️ **Nexo Image** | `/image` | Send a photo to compress, resize, convert format, or strip EXIF metadata. |
| 😂 **Nexo Meme** | `/meme` | Send a photo captioned `top text \| bottom text` for a classic meme. |
| 🔳 **Nexo QR** | `/qr <text>` | Generate a QR code image from text or a link. |
| 🔐 **Nexo Password** | `/password [length]` | Generate a strong random password. |
| 📐 **Nexo Convert** | `/convert 10 km to mi` | Convert between length, weight, volume, and temperature units. |
| ⏰ **Nexo Reminder** | `/remind 10m ...` | Schedule a one-off reminder message. |
| 📖 **Nexo Wiki** | `/wiki <topic>` | Quick Wikipedia summary lookup, no API key needed. |
| 🌤️ **Nexo Weather** | `/weather <city>` | Current weather for any city, no API key needed. |
| 📦 **Nexo Archive** | send a `.zip` | Extracts a zip file sent as a document. |
| 💸 **Nexo Expense** | `/expense add ...` | Log quick expenses with daily/monthly totals. |

More tools are on the way — see [Roadmap](#roadmap-planned-tools) below.

---

## 1. Install Termux on your phone

Don't use the Play Store version — it's outdated and broken for this use case.
Install from **F-Droid** instead:

1. Open your phone's browser and go to `f-droid.org`
2. Download and install the F-Droid app (your phone will warn about
   "installing unknown apps" — allow it for your browser just for this)
3. Open F-Droid, search for **Termux**, and install it
4. In F-Droid, also search for and install **Termux:Boot** and
   **Termux:API** (same publisher — needed later for auto-start and battery
   control)

## 2. Stop Android from killing the bot in the background

Android aggressively kills background apps to save battery, which would stop
the bot. Do this once:

1. **Settings → Apps → Termux → Battery** → set to **Unrestricted**
2. **Settings → Apps → Termux:Boot → Battery** → set to **Unrestricted**
3. **Settings → Battery → Battery optimization** → find Termux → **Don't optimize**
4. Open Termux, swipe it into your **Recent Apps** tray, and tap the pin/lock
   icon so a "clear all" swipe doesn't kill it

(No root required for any of this.)

## 3. Get a bot token from Telegram

1. In Telegram, search for **@BotFather** (the official one, verified checkmark)
2. Send it `/newbot`
3. Give it a display name — e.g. `Nexora Tool Bot` — then a username ending
   in `bot` (e.g. `nexora_tool_bot`)
4. BotFather replies with a token like `7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxx`
   — copy it, you'll need it in step 5. **Keep it private** — anyone with it
   can control your bot.

The bot also sets its own display name to "Nexora Tool Bot" automatically on
startup via the Telegram API, so it'll show that name even if you picked
something else with BotFather.

## 4. Clone and set up the bot

Open Termux and run:

```bash
pkg install -y git
git clone https://github.com/aatef14/nexora-tool-bot.git
cd nexora-tool-bot
bash setup.sh
```

`setup.sh` installs Python, Node, ffmpeg, and all Python dependencies, sets
up storage access, and configures auto-start on reboot.

## 5. Add your bot token

```bash
cp .env.example .env
nano .env
```

Set `BOT_TOKEN=` to the token from step 3. Save with `Ctrl+O`, `Enter`, then
exit with `Ctrl+X`.

## 6. (Recommended) Lock the bot to just you

By default, **anyone who finds your bot's username on Telegram can use it**
— usernames are public and searchable. See [Whitelisting](#whitelisting-restricting-who-can-use-the-bot)
below to restrict it to yourself before going further. The whitelist applies
to every tool in the bot, not just one.

## 7. Run it

```bash
bash bot-start.sh
```

This starts the bot in the background — it keeps running even if you close
Termux. You'll see:
```
Bot started in the background.
View live messages with: bash bot-logs.sh
Stop it with:            bash bot-stop.sh
```

Then in Telegram, open a chat with your bot and send `/start`, then `/tools`
to see the list of available tools — each one has its own command (e.g.
`/link2video`) that shows how to use it.

**Managing the bot going forward:**

| Action | Command |
|---|---|
| Start the bot | `bash bot-start.sh` |
| Watch live activity/logs | `bash bot-logs.sh` (Ctrl+C stops watching, not the bot) |
| Stop the bot | `bash bot-stop.sh` |
| Debug a startup failure | `bash bot-debug.sh` |

If `bash bot-start.sh` reports "Bot failed to start", or the bot just doesn't
seem to respond, run `bash bot-debug.sh` instead — it runs the bot in the
foreground (not backgrounded) so the actual error is printed directly to
your screen instead of only going to `bot.log`. Stop it with `Ctrl+C` once
you've seen the error.

Reboot your phone once after setup — Termux:Boot will auto-start the bot
from then on, so it comes back automatically after a restart or crash.

---

## Project structure

```
nexora-tool-bot/
├── bot.py             # Core: startup, /start, /tools, /id, dispatches to tools, housekeeping
├── webui.py           # Optional local admin web panel
├── core/
│   └── access.py       # Shared whitelist check, used by every tool
├── data/                # Nexo Password Manager / Nexo Expense storage (gitignored, created on demand)
└── tools/
    ├── __init__.py      # TOOLS registry — add new tools here
    ├── password_manager.py, link2video.py, image.py, meme.py
    └── qr.py, password.py, convert.py, reminder.py, wiki.py, weather.py, archive.py, expense.py
```

Each tool is a self-contained module under `tools/` exposing a `NAME`,
`COMMAND`, `SUMMARY`, and a `register(app)` function that wires up its own
Telegram command (e.g. `/link2video`) and handlers. Adding a new tool means
writing one new file and adding it to the `TOOLS` list in
[`tools/__init__.py`](tools/__init__.py) — the `/tools` menu, the bot's
command list, and its description all pick it up automatically.

---

## Using a tool: /tools and per-tool commands

- `/start` — a one-line intro to the bot
- `/tools` — lists every tool currently installed, with its command
- `/status` — bot uptime/health (admin only — see [Whitelisting](#whitelisting-restricting-who-can-use-the-bot))
- `/link2video` — shows usage instructions for Nexo Link2video specifically

You don't actually need to run a tool's command to use it — for
Nexo Link2video, just paste a supported link and the bot picks it up
automatically. The command is there mainly so `/tools` has something to
point at, and so you get a reminder of how that tool works.

### Nexo Link2video: choosing MP4/MP3 and quality

Send any supported video link. The bot detects which platform it's from and
asks you to pick a format:

```
Detected: YouTube
Choose a format:
[ 🎬 MP4 (video) ]  [ 🎵 MP3 (audio) ]
```

Then a quality menu appears:
- **MP4**: Best available, 1080p, 720p, 480p, 360p
- **MP3**: 320 kbps, 192 kbps, 128 kbps

Tap one, and the bot downloads and sends the file back with the title,
uploader, and duration as the caption.

### Nexo Image: compress, resize, convert, strip EXIF

Send any photo — as a photo, or as a file if you want to preserve full
original quality — and the bot asks what to do with it:

```
What would you like to do with it?
[ 🗜 Compress ]  [ 📐 Resize ]
[ 🔁 Convert ]   [ 🧹 Strip EXIF ]
```

- **Compress**: Light / Medium / Heavy (re-encodes as JPEG at a lower quality)
- **Resize**: 75% / 50% / 25% of the original dimensions
- **Convert**: JPEG, PNG, WEBP, or BMP
- **Strip EXIF**: removes camera/location metadata, no further choices needed

The result always comes back as a file (not a photo), so Telegram doesn't
re-compress it a second time on the way out. The caption shows the size
before and after, e.g. `2.4MB → 480KB`.

### Sending a photo: how the bot picks which tool handles it

Two tools react to a photo you send, and the bot picks exactly one based on
the caption, so they never compete for the same photo:

| You send a photo... | Handled by |
|---|---|
| with no caption, or any caption without `\|` | 🖼️ Nexo Image |
| captioned `top text \| bottom text` | 😂 Nexo Meme |

### Nexo Password Manager: an encrypted vault of saved logins

`/password_manager` creates a vault (first time) or signs you in, protected
by a **master password that is never stored anywhere — not even encrypted**.
It only exists transiently in memory each time you sign in, used to derive
the encryption key and verify it against a check value; nothing about it
ever touches disk, so nobody (including you re-reading the vault file, or
anyone with phone access) can recover it after the fact. This also means
**there is no recovery** if you forget it — the vault's entries become
permanently unreadable.

If you forget your master password, the sign-in prompt has a
**"❓ Forgot password? Reset vault"** button — it can't recover the old
entries (nothing could, by design), but it wipes the now-permanently-locked
vault so `/password_manager` can create a fresh one.

Once signed in you get four buttons:

```
🔑 Nexo Password Manager
[ 📋 List passwords ]
[ ➕ Add password ]
[ 🔒 Sign out ]
[ 🗑 Delete vault ]
```

- **Add password** asks for **Purpose**, then **Username**, then
  **Password** — one message each. Every question the bot asks, and your
  answer to it, is deleted from the chat **immediately** (not batched at
  the end) — so at no point does the chat show more than the single
  question currently being asked.
- **List passwords** shows a button per saved entry, labeled by purpose
  (e.g. "Instagram"). Tapping one decrypts and shows the username/password
  in a tap-to-copy code block — that message **auto-deletes after 60
  seconds**.
- **Delete vault** asks for confirmation, then permanently deletes the
  entire vault — every saved entry — and signs you out. There's no undo;
  `/password_manager` afterwards starts a brand new vault from scratch.
- Signing in **expires after 30 seconds of inactivity** — every button tap
  or step of adding an entry resets that timer, so it only signs you out
  when you actually walk away, not mid-task.
- Entries are encrypted with a key derived from your master password via
  PBKDF2 (390,000 iterations) and Fernet (AES-128) — stored in
  `data/password_manager.json`. Without the master password (which, again,
  is never stored), that file is unreadable noise.

**On "delete the whole chat after a week":** this isn't something a bot
can do — Telegram's Bot API hard-caps `deleteMessage` at messages sent
**less than 48 hours ago**, full stop, for every chat type and regardless
of admin rights. No amount of code changes that; it's a platform limit.
Since every sensitive message here is already deleted within seconds
(rather than left to linger for a week), there's nothing sensitive left
for a week-later cleanup to catch anyway. If you want the chat's non-bot
clutter (your own `/password_manager` commands, menu taps, etc.) gone
periodically, Telegram's own client has a manual **"Clear chat history"**
option for that.

### Other tools at a glance

- **Nexo QR**: `/qr https://example.com` — sends back a QR code image.
- **Nexo Password**: `/password` (16 chars) or `/password 24 nosymbols`.
- **Nexo Convert**: `/convert 10 km to mi`, `/convert 100 c to f` — length,
  weight, volume, temperature.
- **Nexo Reminder**: `/remind 2h Call back the client` — fires once; lost
  if the bot restarts before it's due (no persistent job store yet).
- **Nexo Wiki** / **Nexo Weather**: `/wiki <topic>`, `/weather <city>` —
  both free public APIs, no API key needed.
- **Nexo Archive**: send a `.zip` as a file — extracts it (zip only, up to
  20 files, each under `MAX_FILE_SIZE_MB`).
- **Nexo Expense**: `/expense add 12.50 lunch`, `/expense today`,
  `/expense month`, `/expense clear` — persisted to `data/expenses.json`.

---

## Optional: Nexora Tool Bot Admin Portal (web control panel)

Instead of typing `bot-start.sh`/`bot-stop.sh`/`bot-logs.sh` in Termux, you
can run the **Admin Portal** — a small web dashboard on your phone with
Start/Stop/Restart buttons, whitelist management, and a live log view:

```bash
bash web-start.sh
```

Then open **http://localhost:8080** in your phone's own browser (Chrome,
Firefox, whatever). It's not a separate app — it's a small Python web
server (Flask) running inside Termux, same as the bot itself.

Stop it with:
```bash
bash web-stop.sh
```

**Security note:** by default it only binds to `127.0.0.1`, so only your
phone's own browser can reach it. If you set `WEBUI_HOST=0.0.0.0` in `.env`
to access it from another device on the same WiFi (e.g. a laptop), you
**must** also set `WEBUI_PASSWORD` — otherwise anyone on your network could
start/stop your bot.

---

## Whitelisting: restricting who can use the bot

Telegram bots are public by default — anyone who finds the username can
message it and use your phone's bandwidth/battery/storage. To restrict it to
yourself (or a few trusted people), for **all tools at once**:

1. Have the person message your bot with `/id` — it replies with their
   numeric Telegram user ID (e.g. `123456789`) and their username
2. They send you that ID
3. Open the **Admin Portal** (`bash web-start.sh`, then `http://localhost:8080`)
   and add it under **Whitelist** — type the ID, optionally a name to
   label it (e.g. "Atif"), and tap **Add**. The bot restarts automatically
   to apply it.

Prefer the terminal? You can edit `.env` directly instead:
```bash
nano .env
```
Set `ALLOWED_USER_IDS=123456789` (your ID), optionally with a name:
`ALLOWED_USER_IDS=123456789:Atif`. Comma-separate more entries:
`ALLOWED_USER_IDS=123456789:Atif,987654321:Sam`. Then restart:
`bash bot-stop.sh && bash bot-start.sh`

Anyone whose ID isn't in that list gets "This bot is private." instead of a
response, with instructions to send `/id` and pass it to you. Leaving
`ALLOWED_USER_IDS` blank allows anyone to use the bot.

### Admin-only commands: /status

`/status` reports uptime, tools loaded, whitelist size, and log size — but
it's gated separately from the general whitelist above, via `ADMIN_USER_IDS`
in `.env` (same `id` or `id:Name` format). **Being on `ALLOWED_USER_IDS`
does not make you an admin** — this must be set explicitly, and defaults to
nobody if left blank:
```
ADMIN_USER_IDS=123456789:Atif
```
Then restart: `bash bot-stop.sh && bash bot-start.sh`. Anyone else who runs
`/status` gets "This command is for the bot admin only." — and as a UI
nicety, `/status` won't even show up in the `/` command menu for non-admins
(though the actual enforcement is the check in the code, not the menu).

---

## Roadmap (planned tools)

16 tools have shipped so far (table above). Ideas for future additions —
each would land as its own module under `tools/`, following the same
pattern:

- **Nexo PDF** — merge/split PDFs, convert images ↔ PDF, extract text
- **Nexo OCR** — extract text from a photo (receipts, screenshots, signs) —
  needs a system `tesseract` binary, not guaranteed to be on the phone
- **Nexo Translate** — translate text between languages
- **Nexo Shorten** — turn a long URL into a short one (self-hosted)
- **Nexo RSS** — fetch the latest items from a feed URL on demand
- **Nexo FileConvert** — convert between file formats:
  - **Images/Audio/Video** (Pillow/ffmpeg — cheap, ffmpeg already installed for Link2video)
  - **Data**: CSV ↔ JSON ↔ XLSX (pandas/openpyxl)
  - **Archives**: 7Z/RAR support beyond the zip Nexo Archive already handles
  - **Documents**: DOCX/PPTX/XLSX ↔ PDF (needs headless LibreOffice — heavier
    to install on a phone, would ship later as an optional add-on)
- **AI-powered tools** (would need a Claude/LLM API key in `.env`):
  **Nexo AI Chat** (general assistant), **Nexo Summarize** (summarize a
  long article/PDF), **Nexo Ask** (ask about a photo/document)
- **Device-utility tools** (using Termux:API, already a required install):
  **Nexo Device** (battery/storage/uptime), **Nexo Torch**, **Nexo Notify**,
  **Nexo SpeedTest**
- **Privacy-sensitive, needs a deliberate decision before building**:
  Nexo Locate (GPS), Nexo SMS, Nexo Contacts — real value, but only worth
  it if you're confident the whitelist can't be compromised, since they'd
  expose real personal data/hardware on your line

Have a tool you want prioritized, or one to suggest that isn't listed? Open
an issue on the repo.

---

## Notes

- Telegram's standard Bot API caps uploads at 50MB (`MAX_FILE_SIZE_MB` in
  `.env`). To send larger files you'd need to run your own local Bot API
  server with credentials from https://my.telegram.org — not covered here.
- Instagram often rate-limits anonymous requests. If Nexo Link2video
  downloads start failing, export cookies from a logged-in browser session
  and point `INSTAGRAM_COOKIES_FILE` at that file in `.env`.
- Logs are written to `bot.log` in the project folder; it's automatically
  truncated once it exceeds `MAX_LOG_SIZE_MB` (default 20MB) so it won't
  fill up your storage.
- Leftover temp files from any crashed download are swept daily and on
  every startup, so normal use won't accumulate storage over time.
- Nexo Password Manager depends on the `cryptography` package. **Don't let
  pip build it from source on Termux** — its Rust extension can't compile
  there (rustup, which pip tries to auto-fetch, doesn't support Android's
  target triple at all). `setup.sh` already runs `pkg install
  python-cryptography` (a prebuilt version) before `pip install -r
  requirements.txt` to avoid this. If you hit a `maturin`/`rustc` build
  error, run `pkg install python-cryptography` yourself first, then re-run
  `pip install -r requirements.txt` — it'll see cryptography already
  satisfied and skip rebuilding it.
