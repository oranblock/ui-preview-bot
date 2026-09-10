---
name: ui-preview-bot
description: Render SwiftUI and Jetpack Compose snippets to images from a Telegram bot, with no server — a Cloudflare Worker takes the webhook and GitHub Actions draws the picture. Use when asked to preview UI code as an image, build a Telegram bot backed by GitHub Actions, render Compose without an emulator, render SwiftUI without Xcode, or wire a webhook to a repository_dispatch. Repo: oranblock/ui-preview-bot.
---

## What this is

`github.com/oranblock/ui-preview-bot` — send a SwiftUI or Jetpack Compose
snippet to a Telegram bot, get a rendered PNG back with buttons to flip
light/dark and phone/tablet.

```
Telegram  ->  Cloudflare Worker  ->  repository_dispatch  ->  GitHub Actions  ->  sendPhoto
              (auth, classify,          (free)                 (Paparazzi /
               ack the tap, KV)                                 swiftui-render)
```

Nothing runs idle and there is no instance to keep alive. The Worker is the only
always-on piece, and Workers are billed per request.

## Running it

```sh
# self-test without Telegram: renders a stored snippet, sends to the allowlisted chat
gh workflow run render.yml --repo oranblock/ui-preview-bot \
  -f snippet_id=selftest01 -f platform=android -f chat_id=0
```

Setup lives in `worker/setup.sh`. Secrets: `TELEGRAM_BOT_TOKEN` on the repo (to
send), plus `TELEGRAM_BOT_TOKEN`, `GITHUB_TOKEN` and `WEBHOOK_SECRET` on the
Worker.

---

# Hard-won facts

## Do NOT render snippets through an app-build CI harness

The obvious design routes snippets through an existing build-and-run harness.
Don't. Those compile a whole app and boot an emulator or simulator: minutes per
round trip, and 10x runner cost on macOS. They answer "does my app launch and
survive", which is a different question from "draw me this snippet".

| | right tool | wrong tool |
| :--- | :--- | :--- |
| Compose | Paparazzi / LayoutLib on the JVM, ~2.5 min cold | assembleDebug + emulator |
| SwiftUI | swiftui-render (Mac Catalyst), ~1 min | xcodebuild + simulator |

Neither needs an emulator, a simulator, or a device.

## A cron-polled Telegram bot cannot work

This started as a scheduled `getUpdates` poll with no server at all. It fails for
a reason no tuning fixes:

- **`answerCallbackQuery` expires within seconds.** A cron answers minutes later
  and always gets `400: query is too old and response timeout expired`. Every
  button keeps its spinner and looks dead.
- **A new repo's schedule may not fire for the first half hour**, and GitHub
  delays schedules under load. Replies only happened when someone dispatched a
  poll by hand.

Worse, the expired ack was the *first* line of the handler, so its failure
aborted the re-render entirely. Nine taps did nothing at all.

**Use a webhook.** A Cloudflare Worker acknowledges instantly and fires a
`repository_dispatch`. `setWebhook` and `getUpdates` are mutually exclusive, so
the poller must be deleted, not left as a fallback.

## repository_dispatch needs Contents, not Actions

A fine-grained token creating a repository dispatch requires **`Contents: read
and write`**. Not Actions. GitHub's refusal names no permission at all:

```
403 Resource not accessible by personal access token
```

Cost a full debugging round. The symptom from the user's side is a bot that
silently ignores every message.

## Never interpolate a user's snippet into a `run:` block

The snippet is arbitrary source from whoever messaged the bot. GitHub pastes
`${{ }}` into the script verbatim *before* bash sees it, so a snippet containing
a quote and a semicolon runs commands on the runner and no quoting prevents it.

Pass it as an **environment variable** and write it with `printf`:

```yaml
env:
  CODE: ${{ github.event.client_payload.code }}
run: printf '%s\n' "$CODE" > /tmp/snippet.kt
```

## A Worker log nobody tails is the same as no log

The 403 above was caught by `console.log` and the handler returned 200, so
Telegram saw success and the user saw silence. Report handler failures **into
the chat**, not only to the log. Use `npx wrangler tail` to watch live.

Always return 200 from a Telegram webhook regardless: a non-2xx makes Telegram
retry, and a retry storm on a bug is worse than a dropped update.

## Telegram details that cost time

- **`curl -o /dev/null` hides `ok:false`.** Telegram answers **200** with
  `{"ok":false,"description":"chat not found"}`. Two self-test runs printed
  "sent" and were green while delivering nothing. Read the body.
- **urllib's `HTTPError` throws the body away**, and the body is where Telegram
  puts the reason. A bare "400 Bad Request" names the failure, not the cause.
- **`callback_data` is capped at 64 bytes**, so it carries an id and flags,
  never code. Store the snippet (KV) and look it up on the tap.
- **Bot privacy mode is ON by default in groups**, so a bot sees only commands,
  mentions and replies. A plain code snippet in a group is invisible with no
  error anywhere. Disable via @BotFather `/setprivacy`, then re-add the bot to
  the group — the setting applies from when it joins.
- **A bot cannot start a conversation.** Message it `/start` once or sends fail 403.
- **`getWebhookInfo`** is the first thing to read when nothing arrives;
  `last_error_message` names it. A 403 there means `secret_token` mismatch.

## Cloudflare blocks unusual clients before your Worker sees them

A plain Python `urllib` POST got `403 error code: 1010` — Cloudflare's bot
signature check, at the edge, never reaching the Worker. The same request via
`curl -A "Mozilla/5.0"` returned `ok`.

**1010 is not your Worker's 403.** I misread it as a secret mismatch and changed
a working secret. Test a Worker with curl and a normal user-agent.

## Concurrency keys must include every axis

`render-<platform>-<snippet>-<theme>-<device>`. Leave out `platform` and
dispatching the iOS render cancels the Android render of the same snippet.
Leave out theme or device and tapping "dark" cancels the "tablet" render.

Collapsing *identical* repeat taps is the desired behaviour; collapsing
different ones is a bug that looks like a flaky bot.

## swiftui-render is a fast path, not a dependency

Real, and it renders genuine iOS SwiftUI by compiling to Mac Catalyst — but 4
stars, no forks, macOS-only, three backends of differing fidelity. It fell back
to the `ImageRenderer` host during normal use on day one.

Keep a fallback that uses nothing outside the SDK. Fewer exotic views survive
it; nothing outside your repo can break it.

---

# Known blockers

| blocker | status |
| :--- | :--- |
| **SwiftUI needs macOS** | Permanent. No Linux implementation exists, so the Apple half costs macOS runner minutes forever. |
| **Compose renders cold each time** | ~2.5 min. Gradle caching helps on repeat runs in the same repo. |
| **One entry point per snippet** | The scaffold calls `Preview()`. A snippet must define `@Composable fun Preview()` or `struct Preview: View`. |
| **`setWebhook` disables `getUpdates`** | Mutually exclusive. Capture your chat id before switching. |

Related: `android-test-harness` and `ios-test-harness` for running whole apps in
CI, which is the different problem this deliberately does not solve.
