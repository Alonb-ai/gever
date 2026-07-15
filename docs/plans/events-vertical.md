# ורטיקל הופעות (`task_type="events"`) — סטטוס ושלב-ב

שכפול מינימלי של תקדים הקולנוע: שלישיית resolve+task+שדות, DRY_RUN בלבד.

## מה קיים (שלב-א, ממתין לריצות חיות)

- **resolve** (`app/automation/resolve.py`): `_EVENT_PLATFORMS` — לאן ראשית
  (`/events/<slug>/<id>`, זרימת רכישה מלאה בעמוד האירוע, נגיש מ-IP זר),
  קופת ת"א גיבוי (`/show/<slug>`). חיתוך זנבות כותרת בלבד — התאריך וההיכל
  נשארים בכוונה (many עם מועדים אמיתיים = רשימת הבחירה של הלקוח).
- **task** (`app/automation/bu_runner.py::_build_concert_task`): תאריך=אירוע בדיד
  (MISSING:date+OPTIONS), קטגוריית מחיר (MISSING:price_category עם מחירים),
  מושבים כמו קולנוע + מפה היררכית, ת"ז (MISSING:id_number), FAILED:sold_out /
  no_event_in_city. המחיר חי במקטע ה-| — אפס שינוי ב-_parse_result.
- **pipeline**: artist/venue ב-extract/schema (בלי time; date לא עוצר שיחה),
  קיר-כרטיס נוקב בסכום לפני התשלום + לינק עטוף + רמז דחיפות, sold_out /
  no_event_in_city ב-_failure_reply (venue כמיקום).
- **ספייק**: `poc/spike_events.py` — DRY_RUN קשיח, ברירת מחדל בלי תאריך
  (מתרגל MISSING:date+OPTIONS על קובי פרץ, שני מועדים בלאן נכון ל-15.07.26).

## שלב-ב (מחוץ לתכולה הנוכחית)

- **איוונטים (eventim.co.il)** דרך פרוקסי IL של Browserbase — כיום 403 Akamai
  ל-IP לא-ישראלי (נבדק 15.07.26). הפלטפורמה הגדולה בארץ; שווה ורטיקל-משנה.
- **Tickchak LIVE** כשכבת discovery — אינדקס מופעים רוחבי כשה-resolve הרגיל
  מחזיר none.
- **sweeper / פקיעת לינק קיר-הכרטיס** מול טיימר החזקת המושבים של הקופות —
  הלינק הממותג חי TTL_S=1800, אבל המושבים משוחררים הרבה קודם. ההתנהגות
  האמיתית (כמה דקות מחזיקים? מה קורה בפקיעה?) תתברר רק בריצה חיה; אז נחליט
  אם צריך הודעת תזכורת/פקיעה.
