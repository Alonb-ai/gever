# ורטיקל הופעות (`task_type="events"`) — פלטפורמה, עיצוב, סטטוס

שכפול מינימלי של תקדים הקולנוע: שלישיית resolve+task+שדות, DRY_RUN בלבד.
מומש במלואו ב-branch `events-vertical` — 7 קומיטים מקומיים, בלי push, בלי אף
ריצת Browserbase/browser-use.

## הפלטפורמה שנבחרה ולמה

- **ראשית: לאן (leaan.co.il)** — `/events/<slug>/<id>`, זרימת רכישה מלאה בעמוד
  האירוע, נגיש מ-IP זר.
- **גיבוי: קופת תל אביב (kupat.co.il / tickets.kupat.co.il)** — `/show/<slug>`.
- **נימוק:** איוונטים (eventim.co.il) היא אמנם בעלת הכיסוי הגדול בישראל (כולל
  60% מזאפה), אבל אומת ישירות (15.07.26) שהאתר מחזיר 403 Forbidden לכל IP
  לא-ישראלי (דף חסימה בסגנון Akamai) — כלומר חסימת אוטומציה/גיאו ידועה מול
  Browserbase. נדחתה לשלב-ב (פרוקסי IL).

## העיצוב

אותו תקדים כמו קולנוע — שלושה מגעים בלבד, אפס שינוי במנגנונים המשותפים:

1. **resolve** — `_EVENT_PLATFORMS` (לאן ראשית, קופת גיבוי) + `resolve_event_url`;
   חיתוך זנבות כותרת בלבד — התאריך וההיכל נשארים בכוונה (many עם מועדים
   אמיתיים = רשימת הבחירה של הלקוח).
2. **task** — `_build_concert_task`: תאריך=אירוע בדיד (MISSING:date+OPTIONS),
   קטגוריית מחיר (MISSING:price_category עם מחירים), מושבים כמו קולנוע + מפה
   היררכית, ת"ז (MISSING:id_number), FAILED:sold_out / no_event_in_city.
   המחיר חי במקטע ה-| — אפס שינוי ב-`_parse_result`.
3. **שדות pipeline** — artist/venue ב-extract/schema (בלי time; date לא עוצר
   שיחה), קיר-כרטיס נוקב בסכום לפני התשלום + לינק עטוף + רמז דחיפות.

## מה מומש (7 קומיטים, לפי סדר)

- **שלב 0 — מיזוג** (`a5a3763`): `cinema-vertical` מוזג; 4 קונפליקטים נפתרו
  לשימור שני הצדדים — `resolve_reservation_url` עובר דרך `_pick` המשותף וממשיך
  ל-fallbackים של Phase 4-lite (מסעדות בלבד) בענף none; קיר-הכרטיס בקולנוע
  אימץ את `live_link.wrap` של main (הטסט עודכן ללינק הממותג); `run_commit`
  שומר heartbeat + פרמטרי קולנוע; טסטים אדיטיביים משני הצדדים
  (+`_fake_search_list` לחוזה).
- **resolve** (`b6f1f66`): `_EVENT_PLATFORMS` + `resolve_event_url` ב-
  `app/automation/resolve.py`, כולל regex-ים לחיתוך זנבות של לאן וקופת.
- **task** (`fd2a948`): `_build_concert_task` ב-`app/automation/bu_runner.py`.
- **book** (`1d339a6`): artist/venue ב-`book_table_bu` + תקרת 900s גם להופעות.
- **pipeline** (`dc59cd2`): extract/schema, routing ל-`resolve_event_url`,
  קיר-כרטיס עם מחיר, `_human` ל-date/price_category/id_number, `_failure_reply`
  עם sold_out / no_event_in_city (venue כמיקום), `_pending_commit` נושא
  artist/venue; +419 שורות טסטים ב-`tests/test_events_pipeline.py`.
- **ספייק** (`0cadbdf`): `poc/spike_events.py` — DRY_RUN קשיח, ברירת מחדל בלי
  תאריך (מתרגל MISSING:date+OPTIONS על קובי פרץ, שני מועדים בלאן נכון ל-15.07.26).
- **ניקיון** (`1214cea`): הסרת סימלינקי venv שנכנסו במיזוג + gitignore.

## מה מחכה לריצות החיות

- ריצת `poc/spike_events.py` ראשונה מול לאן (DRY_RUN) — אימות ה-task,
  ה-OPTIONS של המועדים, וקטגוריות המחיר בדף אמיתי.
- ריצה מול קופת ת"א (גיבוי) — אימות זרימת `/show/<slug>`.
- **sweeper / פקיעת לינק קיר-הכרטיס** מול טיימר החזקת המושבים של הקופות —
  הלינק הממותג חי TTL_S=1800, אבל המושבים משוחררים הרבה קודם. ההתנהגות
  האמיתית (כמה דקות מחזיקים? מה קורה בפקיעה?) תתברר רק בריצה חיה; אז נחליט
  אם צריך הודעת תזכורת/פקיעה.

## שלב-ב (מחוץ לתכולה הנוכחית)

- **איוונטים (eventim.co.il)** דרך פרוקסי IL של Browserbase — כיום 403 Akamai
  ל-IP לא-ישראלי (נבדק 15.07.26). הפלטפורמה הגדולה בארץ; שווה ורטיקל-משנה.
- **Tickchak LIVE** כשכבת discovery — אינדקס מופעים רוחבי כשה-resolve הרגיל
  מחזיר none.
