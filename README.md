# גבר / Gever

> יש לך גבר שיעשה את זה.

עוזר אישי ב‑WhatsApp בעברית שמבצע משימות באינטרנט במקום המשתמש:
המשתמש שולח הודעה אחת — גבר נכנס לאתר, ממלא את הטופס, ומחזיר אישור.

**זרימה:** הודעת WhatsApp → Gemini Flash (הבנת כוונה + שאלות הבהרה) →
Browserbase + Stagehand (ביצוע באתר) → אישור חוזר ב‑WhatsApp.

האפיון המלא: [`גבר_MVP_Spec.docx`](גבר_MVP_Spec.docx)

---

## מפת דרכים

| שלב | מה בונים | סטטוס |
|-----|----------|-------|
| **0 — PoC** | Stagehand + Browserbase מול Ontopo. שער go/no-go. | 🎯 עכשיו |
| **1 — תשתית** | FastAPI + WhatsApp webhook, Supabase, Gemini Flash | ⬜ |
| **2 — E2E** | Ontopo action מחווט, פרופיל מוצפן, Stripe | ⬜ |
| **3 — הרחבה** | Leaan / Eventim / 10bis + בטא 10‑20 משתמשים | ⬜ |

**שכבת WhatsApp:** דרך **Twilio Sandbox** — אפס אישורי Meta, מתחילים מיד
כשמגיעים לשלב 1. אין צורך ב‑onboarding מקביל עכשיו; ה‑PoC לא נוגע ב‑WhatsApp.

**החלטות שכבר קיבלנו:**
- מתחילים מ‑Ontopo (חינמי, הפיך, בלי תשלום/ת"ז) — לא מביטוח/כרטיסים.
- לא מאחסנים כרטיס אשראי גולמי — תשלום per‑action או טוקניזציה.
- מודל שמניע את Stagehand: **PoC** = `claude-fable-5` (הכי מדויק במדד Stagehand,
  90.6%, יוני 2026 — אמינות לשער go/no-go). **פרודקשן** = שתי שכבות:
  סוס עבודה זול `gemini-3-flash-preview` + fallback ל‑`claude-fable-5` בדפים קשים.
- WhatsApp דרך **Twilio** (Sandbox מבטל המתנה לאישורי Meta). תשלום דרך
  **Lemon Squeezy** (Merchant of Record — checkout מתארח, לא נוגעים בכרטיסים).

---

## מבנה הפרויקט

```
poc/ontopo_poc.py        שלב 0 — סקריפט ה-PoC העצמאי
app/
  main.py                FastAPI + WhatsApp webhook
  config.py              הגדרות מ-.env
  llm/intent.py          Gemini Flash — הבנה ושיחה
  automation/ontopo.py   Stagehand — ביצוע הזמנה
  whatsapp/client.py     שליחת הודעות (Twilio)
  db/supabase_client.py  + schema.sql
  models/schemas.py      סכמות משותפות
tests/
```

## הרצה — שלב 0 (PoC)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # או: uv pip install stagehand python-dotenv
cp .env.example .env             # מלא BROWSERBASE_API_KEY + MODEL_API_KEY
python poc/ontopo_poc.py
```

מה שצריך כדי להריץ את ה‑PoC:
1. `BROWSERBASE_API_KEY` (+ `BROWSERBASE_PROJECT_ID`) — יש לך.
2. `MODEL_API_KEY` + `MODEL_NAME` — מודל שמניע את Stagehand (Claude Sonnet / Gemini).
3. מסעדה לבדיקה ב‑Ontopo (ה‑PoC רץ ב‑`DRY_RUN` — לא יוצר הזמנה אמיתית).

## הרצה — השרת (שלב 1+)

```bash
uvicorn app.main:app --reload
# GET /health  →  {"status":"ok"}
```

## סטאק

Python 3.11+ · FastAPI · [Stagehand](https://docs.stagehand.dev/v3/sdk/python) +
Browserbase · Gemini Flash · Supabase · WhatsApp via Twilio · Lemon Squeezy
