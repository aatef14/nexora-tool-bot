import os
import subprocess
import threading
import time
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template_string, request

from core.access import (
    add_admin,
    add_allowed,
    approve_request,
    get_admin_entries,
    get_allowed_entries,
    get_requests,
    remove_admin,
    remove_allowed,
    remove_request,
)
from core.tools_state import disable_tool, enable_tool, get_disabled_tools, get_usage_stats
from tools import TOOLS

load_dotenv()

APP_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(APP_DIR, "bot.log")

WEBUI_HOST = os.environ.get("WEBUI_HOST", "127.0.0.1")
WEBUI_PORT = int(os.environ.get("WEBUI_PORT", "8080"))
WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD") or None

app = Flask(__name__)

# The whitelist/admin cards and the live log are re-rendered client-side via
# /fragment after any action (so forms clear naturally) without a full page
# reload. The status badge + log tail additionally auto-poll via /api/status
# every few seconds, but that path patches only those two DOM nodes directly
# — never re-rendering the whole fragment — so it can never wipe out text
# someone is mid-typing into the add-whitelist/add-admin inputs.
APP_FRAGMENT = """
<div class="card status-card" id="status-card">
  <div class="status-row">
    <span class="badge {{ status_class }}" id="status-badge">
      <span class="dot"></span><span id="status-text">{{ status_text }}</span>
    </span>
    <button class="icon-btn" type="button" onclick="refreshAll(true)" title="Refresh now">↻</button>
  </div>
  <div class="actions">
    <button class="primary" type="button" data-action="/start" {{ 'disabled' if running else '' }}>▶ Start</button>
    <button class="danger" type="button" data-action="/stop" {{ '' if running else 'disabled' }}>■ Stop</button>
    <button type="button" data-action="/restart">⟳ Restart</button>
  </div>
</div>

<h3>Pending Requests{% if request_entries %} <span class="count-badge">{{ request_entries|length }}</span>{% endif %}</h3>
<div class="card">
  {% if request_entries %}
  <ul class="entry-list">
    {% for uid, name, username, requested_at in request_entries %}
    <li class="entry-row request-row">
      <span class="entry-avatar request">{{ (name or uid)[0]|upper }}</span>
      <span class="entry-label">
        {% if name %}{{ name }}{% else %}{{ uid }}{% endif %}
        {% if username %}<span class="uid-muted">@{{ username }}</span>{% endif %}
        <br><span class="uid-muted">ID {{ uid }} · requested {{ requested_at }}</span>
      </span>
      <div class="request-actions">
        <button class="small primary" type="button" data-action="/requests/approve" data-user-id="{{ uid }}">✅ Approve</button>
        <button class="small danger" type="button" data-action="/requests/deny" data-user-id="{{ uid }}">❌ Deny</button>
      </div>
    </li>
    {% endfor %}
  </ul>
  {% else %}
  <div class="banner info">No pending requests.</div>
  {% endif %}
  <p class="hint">A non-whitelisted user who tries to use the bot shows up here automatically — no need for them to send you their ID manually.</p>
</div>

<h3>Whitelist</h3>
<div class="card">
  {% if allowed_entries %}
  <ul class="entry-list">
    {% for uid, name in allowed_entries %}
    <li class="entry-row">
      <span class="entry-avatar">{{ (name or uid)[0]|upper }}</span>
      <span class="entry-label">{% if name %}{{ name }} <span class="uid-muted">({{ uid }})</span>{% else %}{{ uid }}{% endif %}</span>
      <button class="small danger" type="button" data-action="/whitelist/remove" data-user-id="{{ uid }}">Remove</button>
    </li>
    {% endfor %}
  </ul>
  {% else %}
  <div class="banner warning">Whitelist is empty — anyone can use the bot.</div>
  {% endif %}
  <form class="add-form" id="whitelist-add-form" data-action="/whitelist/add">
    <input type="text" name="user_id" placeholder="Telegram user ID" inputmode="numeric">
    <input type="text" name="name" placeholder="Name (optional)">
    <button class="primary" type="submit">Add</button>
  </form>
  <p class="hint">Get an ID by having the person send /id to the bot. Changes take effect immediately, no restart needed.</p>
</div>

<h3>Admins <span class="hint-inline">(can run /status in the bot)</span></h3>
<div class="card">
  {% if admin_entries %}
  <ul class="entry-list">
    {% for uid, name in admin_entries %}
    <li class="entry-row">
      <span class="entry-avatar admin">{{ (name or uid)[0]|upper }}</span>
      <span class="entry-label">{% if name %}{{ name }} <span class="uid-muted">({{ uid }})</span>{% else %}{{ uid }}{% endif %}</span>
      <button class="small danger" type="button" data-action="/admins/remove" data-user-id="{{ uid }}">Remove</button>
    </li>
    {% endfor %}
  </ul>
  {% else %}
  <div class="banner warning">No admins set — /status is unreachable by anyone until you add one.</div>
  {% endif %}
  <form class="add-form" id="admins-add-form" data-action="/admins/add">
    <input type="text" name="user_id" placeholder="Telegram user ID" inputmode="numeric">
    <input type="text" name="name" placeholder="Name (optional)">
    <button class="primary" type="submit">Add</button>
  </form>
  <p class="hint">Being on the whitelist does NOT make someone an admin — this list is separate.</p>
</div>

<h3>Tools <span class="hint-inline">(toggle instantly, no restart)</span></h3>
<div class="card">
  <ul class="entry-list">
    {% for slug, name, emoji, command, enabled, count, last_used in tool_rows %}
    <li class="entry-row tool-row">
      <span class="entry-avatar tool">{{ emoji }}</span>
      <span class="entry-label">
        {{ name }} <span class="uid-muted">/{{ command }}</span>
        <br><span class="uid-muted">Used {{ count }}x{% if last_used %} · last {{ last_used }}{% endif %}</span>
      </span>
      {% if enabled %}
      <button class="small danger" type="button" data-action="/tools/disable" data-slug="{{ slug }}">Disable</button>
      {% else %}
      <button class="small primary" type="button" data-action="/tools/enable" data-slug="{{ slug }}">Enable</button>
      {% endif %}
    </li>
    {% endfor %}
  </ul>
  <p class="hint">A disabled tool tells anyone who tries to use it that it's temporarily off, instead of silently doing nothing.</p>
</div>

<h3>Live Log</h3>
<pre id="log-view">{{ log_tail }}</pre>
"""

PAGE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexora Tool Bot | Admin Portal</title>
<style>
  :root {
    --bg: #0f1115;
    --card: #171a21;
    --card-hover: #1b1f28;
    --card-border: #262a35;
    --text: #e6e8ec;
    --muted: #8b93a7;
    --accent: #4f8cff;
    --accent-hover: #3d75e0;
    --green: #35c471;
    --green-bg: rgba(53, 196, 113, .12);
    --red: #ff5c5c;
    --red-bg: rgba(255, 92, 92, .12);
    --amber: #f5b942;
    --amber-bg: rgba(245, 185, 66, .12);
    --blue-bg: rgba(79, 140, 255, .12);
    --radius: 14px;
    --ease: cubic-bezier(.2, .8, .2, 1);
  }
  * { box-sizing: border-box; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    max-width: 640px;
    margin: 0 auto;
    padding: 1.5rem 1rem 5rem;
    line-height: 1.5;
    -webkit-tap-highlight-color: transparent;
  }
  h1 {
    font-size: 1.4rem;
    display: flex;
    align-items: center;
    gap: .5rem;
    margin-bottom: 1.25rem;
  }
  h3 {
    font-size: .95rem;
    text-transform: uppercase;
    letter-spacing: .04em;
    color: var(--muted);
    margin: 1.75rem 0 .75rem;
    display: flex;
    align-items: baseline;
    gap: .5rem;
  }
  .hint-inline { text-transform: none; letter-spacing: normal; font-size: .78rem; color: #5c6478; }
  .card {
    background: var(--card);
    border: 1px solid var(--card-border);
    border-radius: var(--radius);
    padding: 1.1rem 1.2rem;
    margin-bottom: 1rem;
    transition: background .2s var(--ease), transform .15s var(--ease), box-shadow .2s var(--ease);
    animation: fade-in .35s var(--ease);
  }
  .status-row { display: flex; align-items: center; justify-content: space-between; }
  .badge {
    padding: .35rem .8rem;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    gap: .45rem;
    font-weight: 600;
    font-size: .85rem;
    transition: background .25s var(--ease), color .25s var(--ease);
  }
  .badge.running { background: var(--green-bg); color: var(--green); }
  .badge.stopped { background: var(--red-bg); color: var(--red); }
  .badge.pending { background: var(--amber-bg); color: var(--amber); }
  .dot { width: .5rem; height: .5rem; border-radius: 50%; background: currentColor; }
  .badge.running .dot { animation: pulse 1.6s ease-in-out infinite; }
  .badge.pending .dot { animation: pulse .8s ease-in-out infinite; }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 currentColor; opacity: 1; }
    50% { box-shadow: 0 0 0 4px transparent; opacity: .55; }
  }
  @keyframes fade-in {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .icon-btn {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--muted);
    font-size: 1.05rem;
    cursor: pointer;
    padding: .3rem .5rem;
    border-radius: 8px;
    transition: background .15s var(--ease), color .15s var(--ease), transform .4s var(--ease);
  }
  .icon-btn:hover { background: #232733; color: var(--text); }
  .icon-btn.spinning { animation: spin .6s linear; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .banner {
    padding: .7rem 1rem;
    border-radius: 10px;
    margin-bottom: 1rem;
    font-size: .9rem;
    animation: fade-in .25s var(--ease);
  }
  .banner.warning { background: var(--amber-bg); color: var(--amber); }
  .banner.info { background: var(--blue-bg); color: var(--accent); }
  .count-badge {
    background: var(--red);
    color: #fff;
    border-radius: 999px;
    padding: .05rem .5rem;
    font-size: .75rem;
    font-weight: 700;
    letter-spacing: normal;
    text-transform: none;
    vertical-align: middle;
    animation: pop-in .25s var(--ease);
  }
  @keyframes pop-in {
    from { transform: scale(.5); opacity: 0; }
    to { transform: scale(1); opacity: 1; }
  }
  .actions { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .9rem; }
  button {
    appearance: none;
    border: none;
    border-radius: 10px;
    padding: .65rem 1.1rem;
    font-size: .92rem;
    font-weight: 600;
    cursor: pointer;
    background: #232733;
    color: var(--text);
    transition: background .15s var(--ease), transform .1s var(--ease), opacity .15s var(--ease);
  }
  button:hover:not(:disabled) { background: #2c313f; }
  button:active:not(:disabled) { transform: scale(.96); }
  button:disabled { opacity: .35; cursor: not-allowed; }
  button.primary { background: var(--accent); color: #fff; }
  button.primary:hover:not(:disabled) { background: var(--accent-hover); }
  button.danger { background: var(--red-bg); color: var(--red); }
  button.danger:hover:not(:disabled) { background: rgba(255, 92, 92, .22); }
  button.small { padding: .4rem .8rem; font-size: .8rem; }
  button.is-loading { position: relative; color: transparent !important; pointer-events: none; }
  button.is-loading::after {
    content: "";
    position: absolute;
    top: 50%; left: 50%;
    width: 14px; height: 14px;
    margin: -7px 0 0 -7px;
    border-radius: 50%;
    border: 2px solid rgba(255,255,255,.35);
    border-top-color: #fff;
    animation: spin .6s linear infinite;
  }
  .add-form { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .5rem; }
  .add-form input[type=text] { min-width: 140px; }
  .uid-muted { color: var(--muted); font-weight: 400; font-size: .85rem; }
  input[type=text] {
    flex: 1;
    padding: .6rem .8rem;
    border-radius: 10px;
    border: 1px solid var(--card-border);
    background: #10131a;
    color: var(--text);
    font-size: .95rem;
    transition: border-color .15s var(--ease), box-shadow .15s var(--ease);
  }
  input[type=text]:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--blue-bg); }
  ul.entry-list { list-style: none; padding: 0; margin: 0; }
  .entry-row {
    display: flex;
    align-items: center;
    gap: .65rem;
    padding: .55rem 0;
    border-bottom: 1px solid var(--card-border);
    font-variant-numeric: tabular-nums;
    animation: fade-in .25s var(--ease);
  }
  .entry-row:last-of-type { border-bottom: none; }
  .entry-avatar {
    width: 1.8rem; height: 1.8rem;
    border-radius: 50%;
    background: var(--blue-bg);
    color: var(--accent);
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: .8rem;
    flex-shrink: 0;
  }
  .entry-avatar.admin { background: var(--amber-bg); color: var(--amber); }
  .entry-avatar.request { background: var(--red-bg); color: var(--red); }
  .entry-avatar.tool { background: #232733; font-size: 1rem; }
  .entry-label { flex: 1; }
  .request-row { align-items: flex-start; }
  .request-row .entry-label { line-height: 1.4; }
  .request-actions { display: flex; gap: .4rem; flex-shrink: 0; }
  .hint { color: var(--muted); font-size: .8rem; margin-top: .6rem; }
  pre {
    background: #0a0c10;
    color: #c7ccd8;
    padding: 1rem;
    border-radius: var(--radius);
    overflow-x: auto;
    max-height: 360px;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: .78rem;
    border: 1px solid var(--card-border);
    margin: 0;
  }
  #toasts {
    position: fixed;
    left: 50%;
    bottom: 1.25rem;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    gap: .5rem;
    z-index: 100;
    width: min(560px, calc(100% - 2rem));
  }
  .toast {
    background: #1e2330;
    border: 1px solid var(--card-border);
    color: var(--text);
    padding: .75rem 1rem;
    border-radius: 12px;
    font-size: .88rem;
    box-shadow: 0 8px 24px rgba(0,0,0,.35);
    animation: toast-in .25s var(--ease);
  }
  .toast.error { border-color: rgba(255, 92, 92, .4); color: var(--red); }
  .toast.leaving { animation: toast-out .2s var(--ease) forwards; }
  @keyframes toast-in {
    from { opacity: 0; transform: translateY(8px) scale(.98); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }
  @keyframes toast-out {
    to { opacity: 0; transform: translateY(6px) scale(.98); }
  }
</style>
</head>
<body>

<h1>🛠️ Nexora Tool Bot | Admin Portal</h1>

<div id="app">
""" + APP_FRAGMENT + """
</div>

<div id="toasts"></div>

<script>
function showToast(message, isError) {
  const container = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' error' : '');
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 220);
  }, 3200);
}

async function refreshFragment() {
  const res = await fetch('/fragment', { credentials: 'same-origin' });
  if (!res.ok) return;
  document.getElementById('app').innerHTML = await res.text();
}

async function refreshStatusOnly() {
  // Patches just the badge + log text directly (never re-renders the whole
  // fragment) so passive polling can never wipe out an in-progress add-form.
  try {
    const res = await fetch('/api/status', { credentials: 'same-origin' });
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById('status-badge');
    const text = document.getElementById('status-text');
    const logView = document.getElementById('log-view');
    if (badge && !badge.dataset.pending) {
      badge.className = 'badge ' + (data.running ? 'running' : 'stopped');
      text.textContent = data.running ? 'RUNNING' : 'STOPPED';
      const startBtn = document.querySelector('[data-action="/start"]');
      const stopBtn = document.querySelector('[data-action="/stop"]');
      if (startBtn) startBtn.disabled = data.running;
      if (stopBtn) stopBtn.disabled = !data.running;
    }
    if (logView) logView.textContent = data.log_tail;
  } catch (e) { /* offline blip — next poll will catch up */ }
}

async function refreshAll(spin) {
  if (spin) {
    const btn = document.querySelector('.icon-btn');
    if (btn) { btn.classList.remove('spinning'); void btn.offsetWidth; btn.classList.add('spinning'); }
  }
  await refreshFragment();
}

function setPendingBadge(label) {
  const badge = document.getElementById('status-badge');
  const text = document.getElementById('status-text');
  if (!badge) return;
  badge.className = 'badge pending';
  badge.dataset.pending = '1';
  text.textContent = label;
  setTimeout(() => { if (badge) delete badge.dataset.pending; }, 6000);
}

const PENDING_LABELS = { '/start': 'STARTING…', '/stop': 'STOPPING…', '/restart': 'RESTARTING…' };

async function runAction(action, btn, form) {
  if (btn) { btn.classList.add('is-loading'); btn.disabled = true; }

  const body = new URLSearchParams();
  if (btn && btn.dataset.userId) body.set('user_id', btn.dataset.userId);
  if (btn && btn.dataset.slug) body.set('slug', btn.dataset.slug);
  if (form) new FormData(form).forEach((v, k) => body.set(k, v));

  if (PENDING_LABELS[action]) setPendingBadge(PENDING_LABELS[action]);

  try {
    const res = await fetch(action, { method: 'POST', body, credentials: 'same-origin' });
    const data = await res.json();
    showToast(data.message, !data.ok);
    if (form) form.reset();
    await refreshFragment();
  } catch (err) {
    showToast('Request failed — check your connection.', true);
    if (btn) { btn.classList.remove('is-loading'); btn.disabled = false; }
  }
}

// Standalone action buttons (start/stop/restart, per-row remove) — these
// are never inside a <form>, so a plain click is the only signal.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-action]');
  if (!btn || btn.disabled || btn.closest('form')) return;
  runAction(btn.dataset.action, btn, null);
});

// The two "Add" forms — handled on 'submit' (not 'click') so this also
// works when Enter is pressed in an input, not just a button tap. Clicking
// the submit button fires both a click and a submit event; only reacting
// here (and not in the click handler above, which explicitly skips buttons
// inside a form) avoids sending the request twice.
document.addEventListener('submit', (e) => {
  const form = e.target.closest('form[data-action]');
  if (!form) return;
  e.preventDefault();
  runAction(form.dataset.action, form.querySelector('button[type=submit]'), form);
});

setInterval(refreshStatusOnly, 3000);
</script>

</body>
</html>
"""


def check_auth(password: str) -> bool:
    return password == WEBUI_PASSWORD


def authenticate() -> Response:
    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Nexora Tool Bot Admin Portal"'},
    )


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if WEBUI_PASSWORD:
            auth = request.authorization
            if not auth or not check_auth(auth.password):
                return authenticate()
        return f(*args, **kwargs)

    return decorated


def is_running() -> bool:
    result = subprocess.run(["pgrep", "-f", "python bot.py"], capture_output=True)
    return result.returncode == 0


def tail_log(lines: int = 50) -> str:
    if not os.path.exists(LOG_PATH):
        return "(no log yet)"
    with open(LOG_PATH, "r", errors="ignore") as f:
        return "".join(f.readlines()[-lines:]) or "(empty)"


def restart_bot(only_if_running: bool = False) -> None:
    if only_if_running and not is_running():
        return
    subprocess.run(["bash", "bot-stop.sh"], cwd=APP_DIR)
    # bot-stop.sh's pkill returns immediately, but the process can take a
    # moment to actually exit. Starting again too soon makes bot-start.sh's
    # own "already running" check see the still-dying old process and
    # abort — this was the actual cause of restarts feeling flaky/silent.
    # Poll for it to actually be gone instead of guessing a fixed delay.
    for _ in range(25):  # up to ~5s
        if not is_running():
            break
        time.sleep(0.2)
    subprocess.run(["bash", "bot-start.sh"], cwd=APP_DIR)


def restart_bot_async(only_if_running: bool = False) -> None:
    """Runs restart_bot in a background thread so the HTTP request that
    triggered it returns immediately instead of blocking the browser for
    several seconds (bot-stop.sh + the exit poll above + bot-start.sh's own
    startup confirmation delay)."""
    threading.Thread(target=restart_bot, kwargs={"only_if_running": only_if_running}, daemon=True).start()


def build_context() -> dict:
    """Shared context for both the full page (index) and the /fragment
    endpoint used for AJAX refreshes — they must render identically, or the
    initial page load can show stale/empty placeholders (status, whitelist,
    admins, pending requests) until some unrelated action happens to
    trigger a fragment refresh."""
    running = is_running()
    return dict(
        running=running,
        status_class="running" if running else "stopped",
        status_text="RUNNING" if running else "STOPPED",
        log_tail=tail_log(),
        allowed_entries=[(str(e["id"]), e["name"]) for e in get_allowed_entries()],
        admin_entries=[(str(e["id"]), e["name"]) for e in get_admin_entries()],
        request_entries=[
            (str(r["id"]), r.get("name", ""), r.get("username", ""), r.get("requested_at", "")[:16].replace("T", " "))
            for r in get_requests()
        ],
        tool_rows=_build_tool_rows(),
    )


def _build_tool_rows() -> list[tuple]:
    disabled = set(get_disabled_tools())
    usage = get_usage_stats()
    rows = []
    for tool in TOOLS:
        stats = usage.get(tool.SLUG, {})
        rows.append(
            (
                tool.SLUG,
                tool.NAME,
                tool.EMOJI,
                tool.COMMAND,
                tool.SLUG not in disabled,
                stats.get("count", 0),
                (stats.get("last_used") or "")[:16].replace("T", " "),
            )
        )
    return rows


@app.route("/")
@requires_auth
def index():
    return render_template_string(PAGE, **build_context())


@app.route("/fragment")
@requires_auth
def fragment():
    return render_template_string(APP_FRAGMENT, **build_context())


@app.route("/api/status")
@requires_auth
def api_status():
    return jsonify({"running": is_running(), "log_tail": tail_log()})


@app.route("/start", methods=["POST"])
@requires_auth
def start():
    threading.Thread(target=lambda: subprocess.run(["bash", "bot-start.sh"], cwd=APP_DIR), daemon=True).start()
    return jsonify({"ok": True, "message": "Starting…"})


@app.route("/stop", methods=["POST"])
@requires_auth
def stop():
    threading.Thread(target=lambda: subprocess.run(["bash", "bot-stop.sh"], cwd=APP_DIR), daemon=True).start()
    return jsonify({"ok": True, "message": "Stopping…"})


@app.route("/restart", methods=["POST"])
@requires_auth
def restart():
    restart_bot_async()
    return jsonify({"ok": True, "message": "Restarting…"})


@app.route("/whitelist/add", methods=["POST"])
@requires_auth
def whitelist_add():
    new_id = request.form.get("user_id", "").strip()
    name = request.form.get("name", "").strip()
    if not new_id.isdigit():
        return jsonify({"ok": False, "message": f"'{new_id}' is not a valid numeric Telegram ID."})

    if not add_allowed(int(new_id), name):
        return jsonify({"ok": False, "message": f"{new_id} is already whitelisted."})

    label = f"{new_id} ({name})" if name else new_id
    return jsonify({"ok": True, "message": f"Added {label} to the whitelist — takes effect immediately."})


@app.route("/whitelist/remove", methods=["POST"])
@requires_auth
def whitelist_remove():
    remove_id = request.form.get("user_id", "").strip()
    if remove_id.isdigit() and remove_allowed(int(remove_id)):
        return jsonify({"ok": True, "message": f"Removed {remove_id} from the whitelist — takes effect immediately."})
    return jsonify({"ok": False, "message": "That entry was already gone."})


@app.route("/admins/add", methods=["POST"])
@requires_auth
def admins_add():
    new_id = request.form.get("user_id", "").strip()
    name = request.form.get("name", "").strip()
    if not new_id.isdigit():
        return jsonify({"ok": False, "message": f"'{new_id}' is not a valid numeric Telegram ID."})

    if not add_admin(int(new_id), name):
        return jsonify({"ok": False, "message": f"{new_id} is already an admin."})

    label = f"{new_id} ({name})" if name else new_id
    return jsonify(
        {
            "ok": True,
            "message": f"Added {label} as an admin — takes effect immediately. "
            "Restart the bot to also add /status and /request_list to their command menu.",
        }
    )


@app.route("/admins/remove", methods=["POST"])
@requires_auth
def admins_remove():
    remove_id = request.form.get("user_id", "").strip()
    if remove_id.isdigit() and remove_admin(int(remove_id)):
        return jsonify({"ok": True, "message": f"Removed {remove_id} from admins — takes effect immediately."})
    return jsonify({"ok": False, "message": "That entry was already gone."})


@app.route("/requests/approve", methods=["POST"])
@requires_auth
def requests_approve():
    user_id = request.form.get("user_id", "").strip()
    if user_id.isdigit() and approve_request(int(user_id)):
        return jsonify({"ok": True, "message": f"Approved {user_id} — added to the whitelist, takes effect immediately."})
    return jsonify({"ok": False, "message": "That request is no longer there."})


@app.route("/requests/deny", methods=["POST"])
@requires_auth
def requests_deny():
    user_id = request.form.get("user_id", "").strip()
    if user_id.isdigit() and remove_request(int(user_id)):
        return jsonify({"ok": True, "message": f"Denied {user_id}'s request."})
    return jsonify({"ok": False, "message": "That request is no longer there."})


@app.route("/tools/disable", methods=["POST"])
@requires_auth
def tools_disable_route():
    slug = request.form.get("slug", "").strip()
    if disable_tool(slug):
        return jsonify({"ok": True, "message": f"Disabled {slug} — takes effect immediately, no restart needed."})
    return jsonify({"ok": False, "message": f"{slug} was already disabled."})


@app.route("/tools/enable", methods=["POST"])
@requires_auth
def tools_enable_route():
    slug = request.form.get("slug", "").strip()
    if enable_tool(slug):
        return jsonify({"ok": True, "message": f"Enabled {slug} — takes effect immediately."})
    return jsonify({"ok": False, "message": f"{slug} was already enabled."})


if __name__ == "__main__":
    if WEBUI_HOST != "127.0.0.1" and not WEBUI_PASSWORD:
        print(
            "WARNING: WEBUI_HOST is not 127.0.0.1 but WEBUI_PASSWORD is unset. "
            "Anyone on your network can start/stop the bot. Set WEBUI_PASSWORD in .env."
        )
    # threaded=True so the page (and other actions) stay responsive while a
    # start/stop/restart is running in its background thread, instead of
    # the single-threaded dev server queuing every request behind it.
    app.run(host=WEBUI_HOST, port=WEBUI_PORT, threaded=True)
