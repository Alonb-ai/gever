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
| **0 — PoC** | Stagehand + Browserbase מול Ontopo. שער go/no-go. | ✅ בוצע |
| **1 — תשתית** | FastAPI + WhatsApp webhook, Supabase, Gemini Flash | 🎯 עכשיו |
| **2 — E2E** | Ontopo action מחווט, פרופיל מוצפן, Lemon Squeezy | ⬜ |
| **3 — הרחבה** | Leaan / Eventim / 10bis + בטא 10‑20 משתמשים | ⬜ |

**שכבת WhatsApp:** דרך **Meta Cloud API** — מספר בדיקה + webhook ישירות מול
ה‑Graph API, בלי Twilio. מתחילים מיד כשמגיעים לשלב 1.

**Backlog — "גבר שמכיר אותך" (דורש Supabase מחובר, כרגע no-op):**
- *שיחת נחיתה ראשונה* — במגע הראשון גבר אוסף פרופיל מלא (מייל, טלפון, מגבלות אוכל,
  אזור מגורים, מצב זוגי) ומתעד אותו ב‑Supabase.
- *טעינת קונטקסט בכל שיחה* — בתחילת כל שיחה הפרופיל נטען ל‑seed, וגבר מתייחס אליו
  ברמיזות עדינות במקום שמתאים (לא אגרסיבי, לא מאולץ) — תחושה שמישהו בצד זוכר אותך.
  התשתית החלקית קיימת (`_profile_block`/`_seed_from` ב‑`pipeline.py`); חסר onboarding ייעודי + מפתחות Supabase.

**שיווק והפצה:** ראה [`docs/MARKETING.md`](docs/MARKETING.md) — ערוצים (IG/X,
ממומן, IRL), סרטון דמו ב‑Remotion, דף נחיתה, לוגו.

**החלטות שכבר קיבלנו:**
- מתחילים מ‑Ontopo (חינמי, הפיך, בלי תשלום/ת"ז) — לא מביטוח/כרטיסים.
- לא מאחסנים כרטיס אשראי גולמי — תשלום per‑action או טוקניזציה.
- מודלים: **שיחה מול המשתמש** = `gemini-2.5-flash` (עברית מדוברת חזקה, זול;
  `gemini-2.5-flash-lite` כאופציה להוזלה). **מנוע הדפדפן (Stagehand)** =
  `claude-sonnet-4-6`. נמנעים ממודלים סיניים לשיחה — עברית חלשה שוברת את הפרסונה.
- WhatsApp דרך **Meta Cloud API**. תשלום דרך
  **Lemon Squeezy** (Merchant of Record — checkout מתארח, לא נוגעים בכרטיסים).

---

## מבנה הפרויקט

```
poc/spike_browseruse.py  שלב 0 — ספייק ה-PoC העצמאי (browser-use)
app/
  main.py                FastAPI + WhatsApp webhook
  config.py              הגדרות מ-.env
  llm/intent.py          Gemini Flash — הבנה ושיחה
  automation/ontopo.py   Stagehand — ביצוע הזמנה
  whatsapp/client.py     שליחת הודעות (Meta Graph API)
  models/schemas.py      סכמות משותפות
tests/
```

## הרצה — שלב 0 (PoC)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                 # או: uv pip install stagehand python-dotenv
cp .env.example .env             # מלא BROWSERBASE_API_KEY + MODEL_API_KEY
python poc/spike_browseruse.py
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
Browserbase · Gemini Flash · Supabase · WhatsApp via Meta Cloud API · Lemon Squeezy
