#!/usr/bin/env python3
"""The whole bot, run on a schedule instead of on a server.

There is no host. GitHub Actions cannot receive a webhook, so this polls
getUpdates every few minutes, and the repo itself is the database: the update
offset lives in bot/state/offset.txt and snippets live in snippets/, both
committed back by the workflow. That is the entire trick.

The cost is latency. GitHub's shortest cron is 5 minutes and it delays scheduled
runs under load, so a reply can take 5-20 minutes. Nothing here can fix that; it
is the price of having nothing to host.
"""
import base64, hashlib, json, os, pathlib, re, subprocess, sys, urllib.parse, urllib.request

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
REPO  = os.environ["GITHUB_REPOSITORY"]
API   = "https://api.telegram.org/bot" + TOKEN

# Allowlist. This repo is public and the bot answers anyone who finds it, so
# every chat that may use it must be named explicitly.
ALLOW = {c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()}

ROOT     = pathlib.Path(__file__).resolve().parent.parent
OFFSET_F = ROOT / "bot" / "state" / "offset.txt"
SNIP_D   = ROOT / "snippets"


def tg(method, **params):
    data = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
         for k, v in params.items() if v is not None}).encode()
    with urllib.request.urlopen(API + "/" + method, data=data, timeout=30) as r:
        return json.load(r)


def classify(text):
    """Swift or Kotlin, decided on the markers each language cannot fake.

    Order matters: a Compose snippet often mentions `Text(` and `Button(` too,
    so the language-specific declarations are checked first and the shared
    vocabulary is never used on its own.
    """
    if re.search(r"@Composable|androidx\.compose|Modifier\.|\bfun\s+\w+\s*\(", text):
        return "android"
    if re.search(r"import SwiftUI|struct\s+\w+\s*:\s*View|\bsome View\b|\bvar body\b", text):
        return "ios"
    return None


def store(text, platform):
    """Content-addressed, so re-sending the same snippet reuses its id and the
    callback buttons keep working across runs."""
    sid = hashlib.sha256(text.encode()).hexdigest()[:10]
    ext = "kt" if platform == "android" else "swift"
    SNIP_D.mkdir(exist_ok=True)
    (SNIP_D / f"{sid}.{ext}").write_text(text)
    return sid


def keyboard(sid, platform, theme, device):
    """callback_data is capped at 64 bytes by Telegram, so it carries an id and
    two short flags, never the snippet."""
    flip = "light" if theme == "dark" else "dark"
    other = "tablet" if device == "phone" else "phone"
    p = platform[0]
    return {"inline_keyboard": [[
        {"text": ("☀️ light" if flip == "light" else "🌙 dark"),
         "callback_data": f"r|{p}|{sid}|{flip}|{device}"},
        {"text": ("📱 phone" if other == "phone" else "🖥 tablet"),
         "callback_data": f"r|{p}|{sid}|{theme}|{other}"},
    ]]}


def dispatch(sid, platform, theme, device, chat_id, message_id=None):
    """Hand the actual rendering to a workflow. This job is ubuntu-only and
    SwiftUI needs macOS, so rendering cannot happen inline here either way."""
    inputs = {"snippet_id": sid, "platform": platform, "theme": theme,
              "device": device, "chat_id": str(chat_id)}
    if message_id:
        inputs["message_id"] = str(message_id)
    subprocess.run(
        ["gh", "workflow", "run", "render.yml", "--repo", REPO]
        + sum([["-f", f"{k}={v}"] for k, v in inputs.items()], []),
        check=True)


def handle_message(msg):
    chat = str(msg["chat"]["id"])
    text = msg.get("text") or ""
    if ALLOW and chat not in ALLOW:
        return
    if text.startswith("/start") or text.startswith("/help"):
        tg("sendMessage", chat_id=chat, text=(
            "Send me a SwiftUI or Jetpack Compose snippet and I will render it.\n\n"
            "Compose: define @Composable fun Preview()\n"
            "SwiftUI: define struct Preview: View\n\n"
            "Replies take 5-20 min: there is no server, only a cron job."))
        return

    # Strip a markdown code fence if the client sent one.
    body = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text.strip())
    platform = classify(body)
    if not platform:
        tg("sendMessage", chat_id=chat,
           text="I could not tell if that is SwiftUI or Compose. Include the "
                "import, or a @Composable / : View declaration.")
        return

    sid = store(body, platform)
    tg("sendMessage", chat_id=chat,
       text=f"queued {platform} render · {sid}\nthis takes a few minutes")
    dispatch(sid, platform, "dark", "phone", chat)


def handle_callback(cb):
    chat = str(cb["message"]["chat"]["id"])
    if ALLOW and chat not in ALLOW:
        return
    tg("answerCallbackQuery", callback_query_id=cb["id"], text="re-rendering…")
    parts = cb["data"].split("|")
    if len(parts) != 5 or parts[0] != "r":
        return
    _, p, sid, theme, device = parts
    platform = "android" if p == "a" else "ios"
    # message_id is passed through so the render job can replace this image in
    # place with editMessageMedia, rather than stacking a new photo per tap.
    dispatch(sid, platform, theme, device, chat, cb["message"]["message_id"])


def main():
    offset = int(OFFSET_F.read_text().strip() or 0) if OFFSET_F.exists() else 0
    r = tg("getUpdates", offset=offset, timeout=0, allowed_updates=["message", "callback_query"])
    updates = r.get("result", [])
    print(f"{len(updates)} update(s) from offset {offset}")
    for u in updates:
        offset = u["update_id"] + 1
        try:
            if "message" in u:
                handle_message(u["message"])
            elif "callback_query" in u:
                handle_callback(u["callback_query"])
        except Exception as e:
            # One bad update must not wedge the offset forever, or the bot
            # replays the same failure every five minutes until someone notices.
            print(f"::warning::update {u['update_id']} failed: {e}")
    OFFSET_F.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_F.write_text(str(offset) + "\n")
    print(f"offset now {offset}")


if __name__ == "__main__":
    main()
