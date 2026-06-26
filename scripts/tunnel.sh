#!/usr/bin/env bash
# חושף את השרת המקומי (port 8000) ל-WhatsApp דרך ה-dev domain הקבוע של ngrok.
# נועל את הפתרון היציב — אל תחזור ל-localhost.run (URL מתחלף, שובר את ה-webview ב-Meta).
# רקע מלא: docs/ops-tunnel.md
set -euo pipefail

# NGROK_DOMAIN מהסביבה, ואם לא — מ-.env שבשורש הפרויקט.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${NGROK_DOMAIN:-}" && -f "$ROOT/.env" ]]; then
  NGROK_DOMAIN="$(grep -E '^NGROK_DOMAIN=' "$ROOT/.env" | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')"
fi

if [[ -z "${NGROK_DOMAIN:-}" ]]; then
  echo "NGROK_DOMAIN לא מוגדר — קבע אותו ב-.env או בסביבה (ה-dev domain הקבוע מ-ngrok)." >&2
  echo "ראה docs/ops-tunnel.md ל-setup (פעם אחת, ~5 דק')." >&2
  exit 1
fi

exec ngrok http 8000 --url "https://$NGROK_DOMAIN"
