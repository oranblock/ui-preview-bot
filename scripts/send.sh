#!/usr/bin/env bash
# send.sh <dir> <render_rc> — deliver whatever the render produced.
#
# Called with `if: always()`, so its job is to make BOTH outcomes legible: a
# picture on success, and the compiler's complaint on failure. A render that
# fails silently is worse than one that fails loudly, because the person waiting
# five minutes for a reply gets nothing and cannot tell why.
set +e

DIR="$1"; RC="${2:-1}"
API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"

# TELEGRAM_CHAT_ID is an allowlist and may hold several chats; a send needs one.
CHAT="${CHAT%%,*}"

PNG=$(find "$DIR" -type f -name '*.png' -newermt '-30 minutes' | head -1)

# Both buttons flip one axis and keep the other, so callback_data stays inside
# Telegram's 64-byte cap while carrying enough to re-render exactly.
p=${PLATFORM:0:1}
[ "$THEME" = dark ] && flip=light || flip=dark
[ "$DEVICE" = phone ] && other=tablet || other=phone
[ "$flip" = light ] && flip_label='☀️ light' || flip_label='🌙 dark'
[ "$other" = phone ] && other_label='📱 phone' || other_label='🖥 tablet'
KB=$(printf '{"inline_keyboard":[[{"text":"%s","callback_data":"r|%s|%s|%s|%s"},{"text":"%s","callback_data":"r|%s|%s|%s|%s"}]]}' \
      "$flip_label"  "$p" "$SNIPPET_ID" "$flip"  "$DEVICE" \
      "$other_label" "$p" "$SNIPPET_ID" "$THEME" "$other")

CAPTION="${PLATFORM} · ${THEME} · ${DEVICE} · ${SNIPPET_ID}"

if [ "$RC" = 0 ] && [ -n "$PNG" ]; then
  if [ -n "${MSG:-}" ]; then
    # editMessageMedia replaces the picture in place, so tapping a button does
    # not stack a new photo under the old one.
    curl -sS -X POST "${API}/editMessageMedia" \
      -F chat_id="$CHAT" -F message_id="$MSG" \
      -F media="{\"type\":\"photo\",\"media\":\"attach://p\",\"caption\":\"${CAPTION}\"}" \
      -F p="@${PNG}" -F reply_markup="$KB" -o /tmp/tg.json
  else
    curl -sS -X POST "${API}/sendPhoto" \
      -F chat_id="$CHAT" -F photo="@${PNG}" \
      -F caption="$CAPTION" -F reply_markup="$KB" -o /tmp/tg.json
  fi
  if grep -q '"ok":true' /tmp/tg.json 2>/dev/null; then
    echo "sent $PNG"
  else
    # Telegram answers 200 with ok:false, so a silent -o /dev/null reported
    # success for a chat that does not exist. Say what it actually said.
    echo "::error::Telegram rejected the send: $(head -c 300 /tmp/tg.json)"
    exit 1
  fi
  exit 0
fi

# Failure path. The snippet is the user's own code, so quoting the compiler back
# at them is the whole point — unlike the harness repos, where the source is
# private and only counts may be published.
LOG=$(find "$DIR" /tmp -maxdepth 2 -name '*render*.log' -o -maxdepth 2 -name 'sr-build.log' 2>/dev/null | head -1)
ERR=$(grep -E '^e: |error:|Error:' "$LOG" 2>/dev/null | head -12)
[ -n "$ERR" ] || ERR=$(tail -12 "$LOG" 2>/dev/null)
[ -n "$ERR" ] || ERR="render failed with rc=${RC} and produced no log"

curl -sS -X POST "${API}/sendMessage" \
  -F chat_id="$CHAT" \
  -F text="❌ ${CAPTION}
$(printf '%s' "$ERR" | head -c 3000)" -o /dev/null
echo "reported failure rc=$RC"
exit 0
