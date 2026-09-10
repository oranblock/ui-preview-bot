#!/usr/bin/env python3
"""Build the Telegram inline keyboard for a rendered preview.

  keyboard.py <buttons.txt|-> <platform> <snippet_id> <theme> <device> <clicks>

Two rows. The first is appearance, always present. The second is the view's own
buttons, read from what the renderer actually found clickable — so the names
come from the UI rather than from anything written here.

callback_data is capped at 64 BYTES by Telegram, which is the whole reason
clicks travel as indices. A label like "DEPLOY FLEET" would blow the budget
after two taps; "0,3" never does.
"""
import json, sys

src, platform, sid, theme, device, clicks = sys.argv[1:7]
p = platform[0]
clicks = clicks.strip()

flip = "light" if theme == "dark" else "dark"
other = "tablet" if device == "phone" else "phone"

rows = [[
    {"text": "☀️ light" if flip == "light" else "🌙 dark",
     "callback_data": f"r|{p}|{sid}|{flip}|{device}|{clicks}"},
    {"text": "📱 phone" if other == "phone" else "🖥 tablet",
     "callback_data": f"r|{p}|{sid}|{theme}|{other}|{clicks}"},
]]

labels = []
if src != "-":
    try:
        labels = [l.strip() for l in open(src) if l.strip()]
    except OSError:
        labels = []

# Six is a practical ceiling: three per row reads well on a phone, and a view
# with dozens of clickable nodes is a list, where tapping row 27 means nothing.
row = []
for i, label in enumerate(labels[:6]):
    nxt = f"{clicks},{i}" if clicks else str(i)
    cb = f"r|{p}|{sid}|{theme}|{device}|{nxt}"
    # Budget check rather than truncation: a silently trimmed callback_data
    # dispatches the WRONG click, which is worse than not offering the button.
    if len(cb.encode()) > 64:
        continue
    row.append({"text": f"👆 {label[:18]}", "callback_data": cb})
    if len(row) == 3:
        rows.append(row)
        row = []
if row:
    rows.append(row)

if clicks:
    rows.append([{"text": "↺ reset", "callback_data": f"r|{p}|{sid}|{theme}|{device}|"}])

print(json.dumps({"inline_keyboard": rows}))
