# UI Preview Bot

Send a SwiftUI or Jetpack Compose snippet to a Telegram bot, get a rendered
picture back with buttons to flip light/dark and phone/tablet.

**There is no server.** GitHub Actions cannot receive a webhook, so a cron job
polls Telegram and the repository is the database: the update offset lives in
`bot/state/offset.txt`, snippets in `snippets/`, both committed back by the
workflow. Nothing to host, nothing to pay for, nothing to keep alive.

The price is latency. GitHub's shortest cron is five minutes and scheduled runs
are delayed under load, so a reply lands in **5 to 20 minutes**. If that is too
slow, the same code runs as a long-polling process anywhere always-on and
replies instantly; only `bot-poll.yml` becomes a `while true` loop.

```
bot/poll.py                 the whole bot: classify, store, dispatch, reply
.github/workflows/bot-poll.yml   cron every 5 min
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

## The buttons never light up, and still work

Telegram expires a callback query seconds after the tap. This bot answers on a
cron minutes later, so `answerCallbackQuery` always fails with "query is too old"
and the button keeps its loading spinner until the client gives up. There is no
fix inside a serverless design; only an always-on process can acknowledge in
time.

The re-render itself is unaffected. Tap once, wait for the poll, and the photo is
replaced in place via `editMessageMedia`. Tapping repeatedly queues one render
per tap, so tap once.

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

Three secrets, set once:

```
gh secret set TELEGRAM_BOT_TOKEN --repo <owner>/<repo>
gh secret set TELEGRAM_CHAT_ID   --repo <owner>/<repo>   # comma-separated allowlist
```

`TELEGRAM_CHAT_ID` is an **allowlist, not a destination**. This repo is public
and the bot answers whoever finds it, so every chat permitted to use it must be
named. A bot cannot start a conversation, so message it `/start` once or every
send fails 403.

## Status

Scaffolded, not yet proven end to end. Both renderers need the same CI iteration
the harness repos needed — expect the first few runs to fail on toolchain
versions rather than on logic. `render.yml` reports the compiler's own error
back into the chat, so those rounds are readable rather than silent.
