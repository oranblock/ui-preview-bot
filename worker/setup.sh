#!/usr/bin/env bash
# One-time setup. Run from worker/ after `npm i -g wrangler` (or use npx).
set -euo pipefail

echo "1. create the KV namespace and paste its id into wrangler.toml"
echo "   npx wrangler kv namespace create SNIPPETS"
echo
echo "2. set the three secrets"
echo "   npx wrangler secret put TELEGRAM_BOT_TOKEN"
echo "   npx wrangler secret put GITHUB_TOKEN     # fine-grained PAT, Contents: read+write, THIS REPO ONLY"
echo "   npx wrangler secret put WEBHOOK_SECRET   # any random string, e.g. openssl rand -hex 16"
echo
echo "3. deploy"
echo "   npx wrangler deploy"
echo
echo "4. point Telegram at it (this also DISABLES getUpdates — the two are mutually exclusive)"
echo '   curl -sS "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \'
echo '     -d url=https://ui-preview-bot.<your-subdomain>.workers.dev \'
echo '     -d secret_token=$WEBHOOK_SECRET \'
echo "     -d allowed_updates='[\"message\",\"callback_query\"]'"
echo
echo "5. check it took"
echo '   curl -sS "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"'
echo "   last_error_message tells you what is wrong when nothing arrives."
