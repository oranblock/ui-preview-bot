/**
 * Telegram webhook receiver.
 *
 * Telegram pushes an update the moment it happens, so a button tap is
 * acknowledged within its few-second window and the spinner clears. That single
 * fact is why this exists: on a cron the acknowledgement can never arrive in
 * time, and every tap looked dead.
 *
 * The Worker does the least it can. It answers the callback, then fires a
 * repository_dispatch so GitHub Actions does the actual rendering. No queue, no
 * state machine, no instance to keep alive.
 *
 * KV holds snippets, because callback_data is capped at 64 bytes and cannot
 * carry code. A tap sends an id; the Worker looks up the source and passes it
 * back to Actions inline.
 */

const TG = (env, m) => `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${m}`;

async function tg(env, method, body) {
  const r = await fetch(TG(env, method), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

/** Swift or Kotlin, decided on declarations each language cannot fake.
 *  Compose is checked first: a SwiftUI snippet never says @Composable, but
 *  both freely say Text( and Button(, so shared vocabulary is never used alone. */
function classify(t) {
  if (/@Composable|androidx\.compose|Modifier\./.test(t)) return "android";
  if (/import SwiftUI|struct\s+\w+\s*:\s*View|some View|var body/.test(t)) return "ios";
  return null;
}

async function sha10(s) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 10);
}

function keyboard(id, platform, theme, device) {
  const p = platform[0];
  const flip = theme === "dark" ? "light" : "dark";
  const other = device === "phone" ? "tablet" : "phone";
  return {
    inline_keyboard: [[
      { text: flip === "light" ? "☀️ light" : "🌙 dark", callback_data: `r|${p}|${id}|${flip}|${device}` },
      { text: other === "phone" ? "📱 phone" : "🖥 tablet", callback_data: `r|${p}|${id}|${theme}|${other}` },
    ]],
  };
}

/** Hand the render to Actions. The code travels in client_payload, never in a
 *  workflow input, and the workflow writes it from an env var — interpolating
 *  user-supplied source into a `run:` block would be remote code execution on
 *  the runner. */
async function dispatch(env, payload) {
  const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "content-type": "application/json",
      "user-agent": "ui-preview-bot-worker",
    },
    body: JSON.stringify({ event_type: "render", client_payload: payload }),
  });
  if (!r.ok) throw new Error(`dispatch ${r.status}: ${(await r.text()).slice(0, 200)}`);
}

function allowed(env, chat) {
  const list = (env.ALLOWED_CHAT_IDS || "").split(",").map(s => s.trim()).filter(Boolean);
  return list.length === 0 || list.includes(String(chat));
}

async function onMessage(env, msg) {
  const chat = msg.chat.id;
  if (!allowed(env, chat)) return;
  const text = (msg.text || "").trim();
  if (!text) return;

  if (text.startsWith("/start") || text.startsWith("/help")) {
    await tg(env, "sendMessage", { chat_id: chat, text:
      "Send me a SwiftUI or Jetpack Compose snippet and I will render it.\n\n" +
      "Compose:  @Composable fun Preview()\n" +
      "SwiftUI:  struct Preview: View\n\n" +
      "Renders take 1-3 minutes: the picture is drawn by GitHub Actions." });
    return;
  }

  const code = text.replace(/^```[a-zA-Z]*\n/, "").replace(/\n```$/, "");
  const platform = classify(code);
  if (!platform) {
    await tg(env, "sendMessage", { chat_id: chat, text:
      "I cannot tell if that is SwiftUI or Compose. Include the import, or a " +
      "@Composable / : View declaration." });
    return;
  }

  const id = await sha10(code);
  await env.SNIPPETS.put(id, code, { metadata: { platform } });
  await tg(env, "sendMessage", { chat_id: chat, text: `queued ${platform} render · ${id}` });
  await dispatch(env, { platform, theme: "dark", device: "phone", chat_id: String(chat), snippet_id: id, code });
}

async function onCallback(env, cb) {
  const chat = cb.message.chat.id;
  // Answer FIRST and unconditionally. It has a few seconds to land, and every
  // other thing here can take longer than that.
  await tg(env, "answerCallbackQuery", { callback_query_id: cb.id, text: "rendering…" });
  if (!allowed(env, chat)) return;

  const [tag, p, id, theme, device] = (cb.data || "").split("|");
  if (tag !== "r") return;
  const code = await env.SNIPPETS.get(id);
  if (!code) {
    await tg(env, "sendMessage", { chat_id: chat, text: `snippet ${id} has expired — send it again` });
    return;
  }
  await dispatch(env, {
    platform: p === "a" ? "android" : "ios",
    theme, device, chat_id: String(chat),
    message_id: String(cb.message.message_id),
    snippet_id: id, code,
  });
}

export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("ui-preview-bot webhook\n");

    // Telegram echoes this header on every delivery. Without it the endpoint is
    // a public URL that anyone can POST arbitrary updates to.
    if (env.WEBHOOK_SECRET &&
        req.headers.get("x-telegram-bot-api-secret-token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    let update;
    try { update = await req.json(); } catch { return new Response("bad json", { status: 400 }); }

    try {
      if (update.message) await onMessage(env, update.message);
      else if (update.callback_query) await onCallback(env, update.callback_query);
    } catch (e) {
      // Always 200. Telegram retries a non-2xx, and a retry storm on a bug is
      // worse than a dropped update.
      console.log("handler failed:", e.message);
    }
    return new Response("ok");
  },
};
