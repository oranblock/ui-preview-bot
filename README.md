# UI Preview Bot

Send a SwiftUI or Jetpack Compose snippet to a Telegram bot, get a rendered
picture back with buttons to flip light/dark and phone/tablet.

A Cloudflare Worker receives the Telegram webhook and fires a
`repository_dispatch`; GitHub Actions draws the picture. Nothing runs idle and
there is no instance to keep alive.

**This started as a cron job and that design failed.** A scheduled poll cannot
answer a callback query: Telegram expires one within seconds, a cron answers
minutes later, so every button tap kept its spinner and looked dead. Worse, the
schedule on a new repo did not fire at all for the first half hour, so replies
only happened when someone dispatched a poll by hand. The webhook removes both
problems rather than working around them.

```
worker/src/worker.js        webhook: classify, ack the tap, dispatch to Actions
worker/wrangler.toml        KV binding and vars; secrets are set by wrangler
worker/setup.sh             the five setup commands, in order
.github/workflows/render.yml     one job per platform, gated on `platform`
android-preview/            Paparazzi scaffold — Compose on the JVM, no emulator
ios-preview/render.sh       swiftui-render, falling back to ImageRenderer
scripts/send.sh             sendPhoto / editMessageMedia, or the compiler error
```

## Why not the test harnesses

The obvious design routes snippets through
[Android-test-harness](https://github.com/oranblock/Android-test-harness) and
[ios-test-harness](https://github.com/oranblock/ios-test-harness). Don't. Those
compile an entire app and boot an emulator or simulator; a round trip is minutes
and the iOS one bills at 10x. They answer "does my app launch and survive",
which is a different question from "draw me this snippet".

Paparazzi renders Compose on the desktop JVM through LayoutLib in seconds, with
no emulator and no APK. That is the right tool, and it is why the Android half
is fast and free.

## The asymmetry

SwiftUI has no Linux implementation, so the Apple half needs macOS and always
will. `swiftui-render` renders real iOS SwiftUI by compiling to Mac Catalyst,
which is the right idea, but it is a 4-star project with no forks — so it is the
fast path, not a dependency. When it is unavailable the script falls back to a
self-contained `ImageRenderer` host that uses nothing outside the SDK. Fewer
exotic views survive the fallback; nothing outside this repo can break it.

| | Compose | SwiftUI |
| :--- | :--- | :--- |
| runner | ubuntu, 1x | macOS, 10x on private repos |
| renderer | Paparazzi / LayoutLib | swiftui-render, else ImageRenderer |
| emulator or simulator | none | none |
| typical render | seconds | tens of seconds plus a toolchain build |

## Why the snippet never touches a `run:` block

The snippet is arbitrary source from whoever messaged the bot. It reaches the
runner as an environment variable and is written out with `printf`, never
interpolated with `${{ }}`. GitHub pastes an expression into the script verbatim
before bash sees it, so a snippet containing a quote and a semicolon would run
commands on the runner and no amount of quoting would stop it.

## What a snippet must look like

The scaffold calls one entry point, so name it:

```kotlin
@Composable
fun Preview() { Text("hello") }
```

```swift
struct Preview: View {
    var body: some View { Text("hello") }
}
```

Common Compose imports are prepended automatically; `import SwiftUI` likewise.
Anything else your snippet needs, import it yourself.

## Setup

One secret on the repo, for sending the finished picture:

```
gh secret set TELEGRAM_BOT_TOKEN --repo oranblock/ui-preview-bot
```

Then the Worker — `worker/setup.sh` prints the five commands in order. It needs
its own copy of the bot token, a **fine-grained** GitHub token scoped to
**`Contents: read and write`** on this repo alone (creating a repository
dispatch needs Contents, not Actions — GitHub's 403 for this names no
permission at all), and a random `WEBHOOK_SECRET`
which Telegram echoes back on every delivery so the public URL cannot be
spoofed.

`ALLOWED_CHAT_IDS` in `wrangler.toml` is an **allowlist**. The webhook URL is
public and the bot answers whoever reaches it, so name every chat permitted to
use it. A bot cannot start a conversation, so message it `/start` once or every
send fails 403.

Setting the webhook **disables `getUpdates`** — Telegram allows one or the
other, never both. `getWebhookInfo` shows `last_error_message`, which is the
first thing to read when nothing arrives.

## Install as a Claude Code plugin

This repo is also a Claude Code plugin. The `ui-preview-bot` skill carries the
failures behind every decision here, so they are not rediscovered.

```
/plugin marketplace add oranblock/ui-preview-bot
/plugin install ui-preview-bot@ui-preview-bot
```

## Status

Working end to end, deployed and verified:

| stage | |
| :--- | :--- |
| Telegram to Worker | authenticated by `secret_token` |
| Worker to `repository_dispatch` | needs Contents write on the token |
| Compose via Paparazzi | ~2.5 min cold, no emulator |
| SwiftUI via swiftui-render | ~1 min, fallback already used once in normal use |
| photo sent, replaced in place on a tap | `sendPhoto` / `editMessageMedia` |

Taps are acknowledged immediately; the render behind them takes as long as the
table says, which reads as "nothing happened" for a couple of minutes.

## What went wrong getting here

Kept because each cost a round and none was visible where anyone was looking.

- **Cron cannot answer a callback query.** It expires in seconds. The whole
  poll-based design died on this, and the expired ack was aborting the re-render
  on top of it.
- **`repository_dispatch` needs `Contents: read and write`**, not Actions.
  GitHub's 403 names no permission, so the bot just ignored every message.
- **`curl -o /dev/null` hid `ok:false`.** Telegram returns **200** with
  `{"ok":false,"description":"chat not found"}`; two green runs delivered nothing.
- **Cloudflare 1010 is not your Worker's 403.** A Python client was blocked at
  the edge; curl with a normal user-agent passed. Misread as a secret mismatch.
- **A `console.log` nobody tails is not a log.** Handler failures now go to the
  chat.
