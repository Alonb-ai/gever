# Deploy ל-Coolify — צ'קליסט (B2)

היעד: גבר באוויר 24/7 בלי המאק ובלי tunnel. השרת: Coolify על 88.198.116.222.
ה-Dockerfile כבר מוכן (שני venvs, **בלי Chrome** — הדפדפן ב-Browserbase דרך CDP,
אומת חי 2026-07-02 על Ontopo וגם Tabit).

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
