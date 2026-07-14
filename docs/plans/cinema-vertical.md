# ורטיקל קולנוע — סיכום עיצוב + סבבי live

מצב: **success=true** — ריצה חיה מלאה על Browserbase (DRY_RUN) הגיעה עד טופס
הפרטים בפלאנט ראשל"צ ועצרה כנה על `MISSING:last_name`. הקוד על branch
`cinema-vertical` (קומיטים `505c668` + `607e10f`), לא נדחף ולא מוזג.

## העיצוב שנבחר ולמה

עיקרון מנחה: **שכפול מינימלי של פלייבוק המסעדות, לא מערכת חדשה.** כל שכבה
קיבלה הרחבה נקודתית באותו חוזה בדיוק:

- **resolve** (`app/automation/resolve.py`): `_CINEMA_PLATFORMS` — פלאנט
  (כולל `yesplanet` legacy), רב-חן, סינמה סיטי — עם regex לדפי סרט בלבד
  (`/films/...`, `/movie/<id>`), כך שאין צורך בסינון listings.
  `resolve_cinema_url` מחזיר בדיוק את החוזה של `resolve_reservation_url`
  (`one|many|none` + fallback); `_pick` משותף לשני הוורטיקלים.
  שאילתת Brave: `"<סרט> כרטיסים קולנוע"`.
- **task** (`bu_runner._build_cinema_task`): אותם עקרונות — מטרה + חוקי ברזל,
  בלי שמות כפתורים, אותם markers בדיוק. ההרחבות היחידות:
  - בחירת סניף לפי עיר (`FAILED:no_cinema_in_city` אם אין).
  - חלון הקרנה ±90 דק' מהשעה המבוקשת (`FAILED:no_availability` מחוצה לו).
  - פורמט (2D/3D/IMAX/מדובב/כתוביות) = בחירה מהותית → `MISSING:format`
    + שורת `OPTIONS:` מהדף; חריג: אפשרות יחידה נלקחת.
  - מושבים = **ברירת המחדל המוצהרת היחידה** שבה ה-agent כן בוחר: צמודים
    באמצע האולם; אין צמודים / רק בתוספת תשלום → `MISSING:seats` + OPTIONS.
  - `SUMMARY_REACHED <שעה> | <מושבים>` — התוספת היחידה לפורמט שורת הסיום.
- **pipeline** (`app/pipeline.py`): `task_type=cinema` + `movie`/`city`
  בסכמת ה-extract, routing ב-`run_booking`, הודעות קיר-כרטיס/pending עם
  סרט+שעה+מושבים, `_failure_reply` מודע ל-task_type.
- **ספייק** (`poc/spike_cinema.py`): DRY_RUN קשיח (לא פרמטר), שחרור סשן
  Browserbase תמיד בסיום.

למה כך: החוזה (markers, resume, קיר-כרטיס, parse) כבר עבר את מסלול ה-live-QA
של המסעדות; כל סטייה ממנו הייתה קונה מחדש את כל הבאגים שכבר תוקנו שם.

## מהלך הסבבים

### iter 1 — ריצה חיה ראשונה (קומיט `607e10f`)

"חינה אמריקאית" בפלאנט ראשל"צ, 15.7 ~20:00, 2 כרטיסים. הסרט נבחר מראש מול
ה-API הציבורי של פלאנט כסרט שבאמת מוקרן (19:30/21:30, פורמט יחיד).

- resolve חד-משמעי מ-Brave (`planetcinema.co.il/films/american-hina/8256s2r`,
  fallback סינמה סיטי).
- ניווט נקי לחלוטין: **14 צעדים בלי אף לופ** — עוגיות → סניף → תאריך →
  הקרנת 19:30 (בטווח) → "הזמינו כאורח" → 2 פופאפים → מפת מושבים SVG
  (שורה 5, מושבים 7-8, דרך evaluate אחרי קליק ישיר שנכשל פעם אחת) →
  2 כרטיסים רגילים (107 ש"ח) → טופס פרטים.
- עצירה כנה: פלאנט דורש שם משפחה, הלקוח נתן רק "אלון" → `MISSING:last_name`
  לגיטימי, עם סיכום תואם מציאות.
- **הבאג היחיד שנמצא:** ה-agent ערבב שני markers בשורה אחת
  (`SUMMARY_REACHED 19:30 | שורה 5 מושבים 7,8 / MISSING:last_name`) כי תבנית
  הדוגמה הפרידה אלטרנטיבות ב-"/", והזנב זיהם את `details.seats` — טקסט שהיה
  דולף להודעת הלקוח. **תוקן בשניים:**
  1. ה-task: "אחת בלבד מהצורות"; עצירת MISSING/FAILED = שורת סיום לבדה.
  2. `_parse_result`: `re.split` על כל marker
     (`CARD_REQUIRED|MISSING:|FAILED:|BOOKED`) חותך כל זנב אחרי המושבים,
     לא רק CARD_REQUIRED.
  + טסט רגרסיה `test_parse_result_mixed_markers_live_iter1_regression` על
  השורה המעורבת המדויקת. כל הטסטים ירוקים.

הקלטת הריצה: `bu_recordings/1784051108359_142af8/` (steps log, run.gif,
conversation). הסשן שוחרר מיד בסיום.

## מה נשאר לליטוש (עם אלון)

- **להגיע ל-CARD_REQUIRED מלא:** להריץ שוב עם שם מלא (להוסיף שם משפחה לפרטי
  הספייק) — הריצה הנוכחית עצרה צעד אחד לפני קיר התשלום.
- לכסות live גם רב-חן וסינמה סיטי (עד כה רק פלאנט נבדק בפועל).
- תרחישי MISSING:format ו-MISSING:seats בעולם האמיתי (סרט עם כמה פורמטים,
  אולם כמעט מלא) + מסלול pause-resume קולנועי מקצה לקצה מהוואטסאפ.
- ניסוחי ההודעות ללקוח (קיר-כרטיס/pending של קולנוע) — טעונים טעימה של אלון.
- merge ל-main רק אחרי הסבב הנ"ל.

## איך מריצים את הספייק

```bash
# מתוך שורש ה-worktree (בשביל ה-.env):
.venv/bin/python poc/spike_cinema.py ["שם סרט"] ["עיר"] [DD.MM] [HH:MM] [כרטיסים]
# ברירות מחדל: "האודיסאה", ראשון לציון, מחר, 20:00, 2
.venv/bin/python poc/spike_cinema.py "חינה אמריקאית" "ראשון לציון" 15.7 20:00 2
```

DRY_RUN מקודד קשיח בספייק — עצירה ב-CARD_REQUIRED/MISSING/OPTIONS/FAILED היא
הצלחה. הפלט מדפיס resolve, ‏ActionResult‏, נתיב ה-steps log, ומשחרר את סשן
ה-Browserbase אוטומטית. לפני קומיט: `ruff check . && pytest`.
