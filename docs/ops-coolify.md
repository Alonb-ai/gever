# Deploy ל-Coolify — בוצע ✅ (2026-07-02) + מפת הניתוב על השרת

**פרודקשן חי:** `https://geverai.duckdns.org` (health → `{"status":"ok","service":"gever"}`).
Meta Callback מעודכן לשם. WHATSAPP_APP_SECRET מוגדר → אימות חתימת webhook פעיל.
ה-tunnel המקומי (ngrok) = dev בלבד מעכשיו.

## מפת הניתוב על השרת (88.198.116.222 — Elestio VM שמריץ גם n8n!)

⚠️ **פורט 443 שייך ל-nginx של Elestio, לא ל-Traefik של Coolify** — לכן דומיין
שמוגדר רק ב-Coolify לא עובד. המסלול בפועל:

```
Meta → https://geverai.duckdns.org (nginx של Elestio, תעודת LE אוטומטית)
     → proxy_pass http://0.0.0.0:8001 (עריכת server block ייעודי לדומיין,
       Elestio dashboard → Security → Nginx configuration; 3 שורות proxy_pass)
     → container של Coolify (Port Mapping 8001:8000) → uvicorn :8000
```

- הדומיין: DuckDNS (geverai.duckdns.org → 88.198.116.222, חשבון GitHub של אלון).
- הדומיין נוסף ב-Elestio → Custom Domain Names → Manage SSL Domains (מנפיק LE).
- ה-server block של geverai הוא קובץ נפרד — **לא נוגע ב-n8n** (דומיין אחר, בלוק אחר).
- פורט 8001 חסום מבחוץ ע"י חומת האש — בכוונה; רק ה-nginx ניגש מבפנים.
- **redeploy רגיל של קוד = רק Coolify** (Redeploy אחרי push ל-main). ה-nginx של
  Elestio לא קשור לקוד — נוגעים בו רק אם משנים דומיין/פורט.

## הצ'קליסט המקורי (בוצע — נשמר לשחזור)

## צעדים ב-Coolify UI (חד-פעמי)

1. **New Resource → Application → GitHub** → repo `Alonb-ai/gever`, branch `main`,
   Build Pack = Dockerfile. פורט פנימי 8000.
2. **Environment Variables** — להדביק את הערכים מה-.env המקומי (השמות למטה).
3. **Domain** — subdomain על הדומיין של השרת + SSL אוטומטי (Let's Encrypt).
4. **Deploy** → לוודא `GET https://<domain>/health` מחזיר `{"status":"ok"}`.
5. **Meta Callback URL** — dashboard → WhatsApp → Configuration →
   `https://<domain>/webhook` + verify token `gever_verify_2026` → Verify and Save.
   (מרגע זה ה-tunnel המקומי הוא dev בלבד.)
6. **בדיקת המשכיות (B3):** הודעת WhatsApp → גבר עונה מהשרת; redeploy → השיחה
   נמשכת (prefs._chat ב-Supabase).

## משתני env (שמות בלבד — הערכים מה-.env המקומי / חדשים)

| שם | הערה |
|---|---|
| `GEMINI_API_KEY` | אותו מפתח (Tier 1, paid) |
| `BRAVE_API_KEY` | **חובה בפרודקשן** — מנוע ה-resolve; DDG מחזיר 202 אנטי-בוט ל-IP של השרת (נצפה חי 2026-07-02) |
| `GEMINI_MODEL` | `gemini-3.5-flash` |
| `MODEL_NAME` | `google/gemini-3-flash-preview` |
| `BU_BROWSER` | `browserbase` — **חובה**; אין Chrome ב-image |
| `BROWSERBASE_API_KEY` / `BROWSERBASE_PROJECT_ID` | מה-.env |
| `BU_HEADLESS` | `true` |
| `BU_RECORD_DIR` | ריק (אין persist ל-recordings בקונטיינר) או volume |
| `WHATSAPP_ACCESS_TOKEN` | ה-System User token הקבוע (expires_at:0) |
| `WHATSAPP_PHONE_NUMBER_ID` | `1067216693152504` (מספר הטסט, עד שיש מספר אמיתי) |
| `WHATSAPP_VERIFY_TOKEN` | `gever_verify_2026` |
| `WHATSAPP_APP_SECRET` | לאימות חתימת webhook |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | מה-.env |
| `ENCRYPTION_KEY` | ⚠️ **הסופי** — החלפה אחרי בטא = PII ישן אבוד |
| `DEBUG_ERRORS` | `true` לבטא; לכבות לפני קהל |
| `DRY_RUN` | `true` עד סגירה אמיתית מבוקרת (A4) |

הערות: `BU_VENV_PATH` מוגדר ב-Dockerfile (`/opt/bu-venv/bin/python`) — לא צריך ב-env.
`NGROK_DOMAIN` הוא dev בלבד — לא עובר ל-Coolify.
