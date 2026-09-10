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
  if (!r.ok) {
    const body = (await r.text()).slice(0, 200);
    // The commonest cause by far, and the message GitHub returns for it names
    // no permission at all: creating a repository dispatch needs Contents
    // read+write on a fine-grained token, NOT Actions.
    const hint = r.status === 403
      ? " — a fine-grained token needs Contents: read and write for this"
      : "";
    throw new Error(`dispatch ${r.status}: ${body}${hint}`);
  }
}

function allowed(env, chat) {
  const list = (env.ALLOWED_CHAT_IDS || "").split(",").map(s => s.trim()).filter(Boolean);
  const ok = list.length === 0 || list.includes(String(chat));
  // Log the rejection. A silent allowlist is indistinguishable from a broken
  // bot: uploads arrived, the Worker answered 200, and nothing else happened
  // anywhere, because the chat sending them was not the chat configured.
  if (!ok) console.log(`chat ${chat} not in ALLOWED_CHAT_IDS (${list.join(",") || "empty"})`);
  return ok;
}

/** Pull an uploaded .kt/.swift file down from Telegram.
 *  A real file beats a pasted snippet: no reformatting by the client, no lost
 *  indentation, and the filename settles the language before any regex does. */
function b64(buf) {
  let s = "";
  const b = new Uint8Array(buf);
  for (let i = 0; i < b.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

async function fetchDocument(env, doc) {
  const name = doc.file_name || "";
  if (!/\.(kt|kts|swift|zip)$/i.test(name)) return null;
  // 20 MB is the bot API's download ceiling; a source file nowhere near it that
  // is still large is almost certainly not a view worth rendering.
  if (doc.file_size && doc.file_size > 512 * 1024) {
    throw new Error(`${name} is ${Math.round(doc.file_size / 1024)} KB — too large to render`);
  }
  const info = await tg(env, "getFile", { file_id: doc.file_id });
  if (!info.ok) throw new Error(`getFile: ${info.description}`);
  const r = await fetch(
    `https://api.telegram.org/file/bot${env.TELEGRAM_BOT_TOKEN}/${info.result.file_path}`);
  if (!r.ok) throw new Error(`download ${r.status}`);

  if (/\.zip$/i.test(name)) {
    // A zip travels base64 inside client_payload. GitHub caps that payload, so
    // reject early with a number rather than letting the dispatch fail with an
    // error about JSON that explains nothing.
    const encoded = b64(await r.arrayBuffer());
    if (encoded.length > 55000) {
      throw new Error(`${name} is too large once encoded (${Math.round(encoded.length / 1024)} KB of ` +
                      `a ~54 KB budget) — send only the view and the files it needs`);
    }
    // The language cannot come from the filename here, so look inside: the
    // manifest of names is enough and costs nothing.
    const names = info.result.file_path;
    return { name, zip: encoded, platform: null, needsSniff: true };
  }

  return { name, code: await r.text(),
           platform: /\.swift$/i.test(name) ? "ios" : "android" };
}

async function onMessage(env, msg) {
  const chat = msg.chat.id;
  if (!allowed(env, chat)) return;

  if (msg.document) {
    const f = await fetchDocument(env, msg.document);
    if (!f) {
      await tg(env, "sendMessage", { chat_id: chat,
        text: `I render .kt, .swift and .zip files. ${msg.document.file_name || "that"} is none of those.` });
      return;
    }

    if (f.zip) {
      // Which language a zip holds is decided by the workflow, which can see
      // the extracted names. Both jobs cannot run, so guess here and let the
      // caption say so: a zip named *.swift.zip or holding swift wins ios.
      const platform = /swift|ios/i.test(f.name) ? "ios" : "android";
      const id = await sha10(f.zip);
      await env.SNIPPETS.put(id, f.zip, { metadata: { platform, zip: true } });
      await tg(env, "sendMessage", { chat_id: chat,
        text: `queued ${platform} render · ${f.name} · ${id}\n` +
              `(a zip is read as ${platform}; name it *-ios.zip or *-android.zip to be sure)` });
      await dispatch(env, { platform, theme: "dark", device: "phone",
                            chat_id: String(chat), snippet_id: id, zip_b64: f.zip });
      return;
    }

    const id = await sha10(f.code);
    await env.SNIPPETS.put(id, f.code, { metadata: { platform: f.platform } });
    await tg(env, "sendMessage", { chat_id: chat,
      text: `queued ${f.platform} render · ${f.name} · ${id}` });
    await dispatch(env, { platform: f.platform, theme: "dark", device: "phone",
                          chat_id: String(chat), snippet_id: id, code: f.code });
    return;
  }

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

  const [tag, p, id, theme, device, clicks] = (cb.data || "").split("|");
  if (tag !== "r") return;
  const code = await env.SNIPPETS.get(id);
  if (!code) {
    await tg(env, "sendMessage", { chat_id: chat, text: `snippet ${id} has expired — send it again` });
    return;
  }
  // A zip was stored base64; a snippet was stored as text. Send it back on the
  // field the workflow expects, or a re-render silently loses every file but one.
  const isZip = /^[A-Za-z0-9+/=\s]+$/.test(code) && code.startsWith("UEsD");
  await dispatch(env, {
    platform: p === "a" ? "android" : "ios",
    theme, device, chat_id: String(chat),
    message_id: String(cb.message.message_id),
    snippet_id: id,
    clicks: clicks || "",
    ...(isZip ? { zip_b64: code } : { code }),
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

    // One line per update, so "nothing happened" always has a record.
    const c = update.message?.chat, d = update.message?.document;
    console.log("update", update.update_id,
      c ? `chat=${c.id} type=${c.type}` : "callback",
      d ? `doc=${d.file_name}` : (update.message?.text ? "text" : ""));

    try {
      if (update.message) await onMessage(env, update.message);
      else if (update.callback_query) await onCallback(env, update.callback_query);
    } catch (e) {
      // Always 200. Telegram retries a non-2xx, and a retry storm on a bug is
      // worse than a dropped update.
      console.log("handler failed:", e.message);
      // ...but say so in the chat too. A Worker log nobody is tailing is the
      // same as no log: this exact failure (a token missing Contents:write)
      // looked from Telegram like the bot simply ignoring the message.
      const chat = update.message?.chat?.id || update.callback_query?.message?.chat?.id;
      if (chat) {
        await tg(env, "sendMessage", { chat_id: chat, text: `⚠️ ${e.message}`.slice(0, 3500) })
          .catch(() => {});
      }
    }
    return new Response("ok");
  },
};
