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
`Actions: read and write` on this repo alone, and a random `WEBHOOK_SECRET`
which Telegram echoes back on every delivery so the public URL cannot be
spoofed.

`ALLOWED_CHAT_IDS` in `wrangler.toml` is an **allowlist**. The webhook URL is
public and the bot answers whoever reaches it, so name every chat permitted to
use it. A bot cannot start a conversation, so message it `/start` once or every
send fails 403.

Setting the webhook **disables `getUpdates`** — Telegram allows one or the
other, never both. `getWebhookInfo` shows `last_error_message`, which is the
first thing to read when nothing arrives.

## Status

Both renderers are proven end to end: a Compose render and a SwiftUI render were
built and delivered to Telegram with working buttons. `swiftui-render` has
already fallen back to `ImageRenderer` once in normal use, which is why the
fallback is there.

The Worker is written but not yet deployed, so the webhook path is unproven.
Until it is deployed, nothing reaches the bot at all.
