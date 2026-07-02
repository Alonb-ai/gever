# גבר / Gever

> יש לך גבר שיעשה את זה.

עוזר אישי ב‑WhatsApp בעברית שמבצע משימות באינטרנט במקום המשתמש:
המשתמש שולח הודעה אחת — גבר נכנס לאתר, ממלא את הטופס, ומחזיר אישור.

**זרימה:** הודעת WhatsApp → Gemini (הבנת כוונה + שאלות הבהרה) →
browser-use (ניווט אוטונומי בדפדפן, subprocess ב‑`.venv-bu`) → אישור חוזר ב‑WhatsApp.

האפיון המלא: [`גבר_MVP_Spec.docx`](גבר_MVP_Spec.docx)

---

## מפת דרכים

| שלב | מה בונים | סטטוס |
|-----|----------|-------|
| **0 — PoC** | browser-use מנווט את Ontopo אוטונומית עד שלב הכרטיס. שער go/no-go. | ✅ בוצע |
| **1 — תשתית** | FastAPI + WhatsApp webhook (Meta Cloud API), Supabase, Gemini. הלולאה LIVE. | ✅ בוצע |
| **2 — E2E** | הזמנה אמיתית מעבר ל‑DRY_RUN, פרופיל מוצפן, Lemon Squeezy | 🎯 עכשיו |
| **3 — הרחבה** | Leaan / Eventim / 10bis + בטא 10‑20 משתמשים | ⬜ |

**שכבת WhatsApp:** דרך **Meta Cloud API** — מספר בדיקה + webhook ישירות מול
ה‑Graph API, בלי Twilio. חשיפת השרת המקומי דרך tunnel יציב (ngrok dev domain,
**לא** localhost.run) — ראה [`docs/ops-tunnel.md`](docs/ops-tunnel.md).

**שיווק והפצה:** ראה [`docs/MARKETING.md`](docs/MARKETING.md) — ערוצים (IG/X,
ממומן, IRL), סרטון דמו ב‑Remotion, דף נחיתה, לוגו.

**החלטות שכבר קיבלנו:**
- מתחילים מ‑Ontopo (חינמי, הפיך, בלי תשלום/ת"ז) — לא מביטוח/כרטיסים.
- לא מאחסנים כרטיס אשראי גולמי — Lemon Squeezy מארח את ה‑checkout, PII מוצפן ב‑rest (Fernet).
- מודלים (נקבעו — שינוי רק דרך `.env`/Coolify, לא בקוד): **שיחה מול המשתמש** =
  `gemini-3.5-flash` (עברית מדוברת חזקה). **מנוע הדפדפן (browser-use)** =
  `google/gemini-3-flash-preview` (ניצח את ה‑A/B החי על Ontopo). נמנעים ממודלים
  סיניים לשיחה — עברית חלשה שוברת את הפרסונה.
- WhatsApp דרך **Meta Cloud API**. תשלום דרך
  **Lemon Squeezy** (Merchant of Record — checkout מתארח, לא נוגעים בכרטיסים).

---

## מבנה הפרויקט

```
poc/spike_browseruse.py    שלב 0 — ספייק ה-PoC העצמאי (browser-use, Chrome מקומי)
app/
  main.py                  FastAPI + Meta WhatsApp webhook
  config.py                הגדרות מ-.env (pydantic-settings) — מקור יחיד לקונפיג
  pipeline.py              הלולאה הראשית: converse / run_booking / run_commit
  llm/intent.py            Gemini — פרסונת גבר (SYSTEM_PROMPT) + הבנת כוונה
  automation/
    bu_runner.py           בניית המשימה ל-browser-use + פענוח התוצאה (רץ ב-.venv-bu)
    browser_book.py        עטיפת book_table_bu (BU_TIMEOUT_S)
    resolve.py             resolve_reservation_url — Ontopo › Tabit, שואל אם עמום
    ontopo.py              עזרים טהורים (string match לדיסאמביגואציה)
  whatsapp/client.py       שליחת הודעות (Meta Graph API)
  db/memory.py             Supabase דרך PostgREST — פרופיל, שיחה, הזמנות (Fernet)
  models/schemas.py        סכמות משותפות
tests/
```

## הרצה — שלב 0 (PoC)

ה‑PoC רץ עם browser-use מול Chrome מקומי (לא Browserbase, לא Stagehand):

```bash
python3 -m venv .venv-bu && source .venv-bu/bin/activate
pip install browser-use python-dotenv
cp .env.example .env             # מלא GEMINI_API_KEY
python poc/spike_browseruse.py   # רץ ב-DRY_RUN — לא יוצר הזמנה אמיתית
```

## הרצה — השרת (שלב 1+)

```bash
cd ~/Desktop/GeverAI && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# GET /health  →  {"status":"ok"}
# חשיפה ל-WhatsApp (tunnel יציב, לא localhost.run): scripts/tunnel.sh — ראה docs/ops-tunnel.md
```

## סטאק

Python 3.11+ · FastAPI · [browser-use](https://github.com/browser-use/browser-use) ·
Gemini · Supabase · WhatsApp via Meta Cloud API · Lemon Squeezy
