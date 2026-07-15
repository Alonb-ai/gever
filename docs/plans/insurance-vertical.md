# ורטיקל ביטוח (פספורטכארד — ביטוח נסיעות לחו"ל) + פרוטוקול MISSING מרובה-שדות

מסמך המימוש של ה-branch ‏`insurance-vertical`‏ (מבוסס main, **בלי** קוד הקולנוע —
הקולנוע חי בענף `cinema-vertical`, ‏152cb80‏). **אסור להריץ Browserbase/browser-use
חי מהענף הזה עד סבב ה-live הייעודי** — הספייק נכתב אבל לא הורץ.

## 0. הנחות והחלטות-על

1. **מיזוג עתידי מכני:** הריפקטור המשותף הועתק מילה-במילה מענף הקולנוע —
   `_NAV_GENERIC`/`_PERK_BLOCK`/`_DRY_TAIL`/`_COMMIT_TAIL` + dispatch על
   `job["task_type"]` ב-`bu_runner.py`; `_candidate(..., platforms)` +
   `_from_brave(..., platforms)` + `_pick(...)` ב-`resolve.py`; `_timeout_s(job)`
   ב-`browser_book.py`. (ב-main נוספו בינתיים fallbackים לענף none של המסעדות —
   `resolve_reservation_url` קורא ל-`_pick` ומריץ אותם רק על none; התנהגות זהה.)
2. **הפיצ'ר המרכזי: איסוף מרוכז, לא עצירה פר-שדה.** שתי שכבות: (א) חבילת שדות
   שנאספת בשיחה לפני הריצה (`ready=true` רק כשמלאה); (ב) פרוטוקול MISSING
   מרובה-שדות כרשת ביטחון — ה-agent אוסף את **כל** השדות החסרים בדף הנוכחי ועוצר
   פעם אחת פר-דף (טופס מרובה-דפים ⇒ ייתכנו כמה עצירות, אחת לדף — מותר).
3. **resolve = יעד קבוע** (`https://purchase.passportcard.co.il/`), בלי Brave —
   ורטיקל של ספק יחיד, אותו חוזה החזרה בדיוק (`resolve_insurance_url`).
4. **ה-deliverable של recon = הפרמיה.** ה-payload אחרי `SUMMARY_REACHED |`
   (התפר המותר היחיד) נושא את הצעת המחיר, נתפס בשדה הגנרי `extra`
   (בקולנוע נקרא `seats` — במיזוג מאחדים). commit כמעט תמיד נגמר
   ב-`CARD_REQUIRED` → Live View.
5. **מסעדות עובדות בדיוק כמו היום:** שדה בודד = המקרה הפרטי; כל הרחבה
   תואמת-לאחור וכל טסט קיים נשאר ירוק.
6. **PII:** ת"ז/תאריכי לידה לעולם לא ב-URL. ב-MVP לא נשמרים בפרופיל (אין PII at
   rest); ערכים חיים רק ב-flow הרץ. שמירה עתידית בפרופיל = רק Fernet
   (`ENCRYPTION_KEY`). העובדה שהם ממילא ב-`prefs._chat`/`prefs._flow` (הלקוח
   הקליד בצ'אט) — חוב ידוע, לא נפתר כאן.

## 1. פרוטוקול MISSING מרובה-שדות (תואם-לאחור)

חוזה ה-agent — שלוש צורות שורה:

```
FIELD <key>: <תווית השדה בעברית כפי שמופיעה בדף>
OPTIONS <key>: <אפשרות 1> | <אפשרות 2> | <אפשרות 3>
MISSING:<key1>|<key2>|<key3>
```

- שורת הסיום `MISSING:` — כל המפתחות בשורה אחת, מופרדים ב-`|` בלי רווחים, לבדה
  (בלי `SUMMARY_REACHED` לפניה).
- מפתח: אנגלית, `[a-z0-9_]`, ייחודי (`id_number`, `passenger2_birth_date`).
- `OPTIONS <key>:` רק לשדה-בחירה; הצורה הישנה `OPTIONS:` בלי מפתח נשארת תקפה
  (מסעדות — שדה בודד).

צד הפרסור (`_parse_result`): `missing_fields` (רשימה, cap 12), `missing` = השדה
הראשון (כל צרכן קיים עובד ללא שינוי), `options_by_field`, `field_labels`, `extra`
(payload אחרי `|` בשורת ה-SUMMARY_REACHED, עם חיתוך markers שהודבקו — cap 120).
גישור: צורה ממופתחת על שדה בודד ממופה ל-`options` הישן.

צד ה-pipeline: עצירה מרובה ⇒ הודעת `_multi_ask` אחת עם כל הפריטים (בלי רשימת-טאפ);
`_await_answer` נושא `missing_fields`/`answered`/`labels` (`options` ריק ⇒ המסלול
הדטרמיניסטי הישן מדלג); ה-extract מקבל ערוץ `answers` ("<מפתח>: <ערך>");
ההשלמה **דטרמיניסטית** ב-`handle_inbound` — כשכל המפתחות נענו, `run_booking` נורה
עם `form_answers`, וה-resume מזרים אותם ל-intro של ה-task. `_truth_note` במצב
missing מרובה מציג את הרשימה החיה (`remaining`) ומכוון את הפרסונה לבקש רק את החסר.

## 2. שלישיית הביטוח

- **resolve** — `INSURANCE_URL` + `resolve_insurance_url()` (תמיד `one`).
- **task builder** — `_build_insurance_task` ב-`bu_runner.py`: לקוח חדש בלבד;
  יעד→אזור (ספק בדף ⇒ `MISSING:destination_region` + OPTIONS); הצהרת בריאות =
  הצהרה משפטית — עונים "לא" רק לשלוש הקטגוריות שנשאלו בשיחה, כל שאלה אחרת ⇒
  MISSING עם ציטוט הנוסח; הרחבות — רק מה שהתבקש, ביטול סימון-מראש; כישלונות
  ייחודיים `manual_underwriting`/`phone_only`/`blocked`; AGREED חובה על כל
  צ'קבוקס; סיום `SUMMARY_REACHED | <הפרמיה>`.
- **browser_book** — `BU_INSURANCE_TIMEOUT_S=1200`, `_timeout_s(job)`,
  `max_steps=80`, פרמטרים `task_type`/`insurance`/`form_answers`, passthrough
  של `missing_fields`/`options_by_field`/`field_labels`/`extra` ל-details.
- **pipeline** — סכמה: `destination`, `return_date`, `travelers_birth_dates`,
  `health_issues`, `addons`, `answers`; גארדים לפני ריצה (בריאות חיובית /
  גיל 85+ ⇒ הפניה ל-*9912 בלי לשרוף ריצה); דילוג resolve; הודעות quote
  (קיר-כרטיס ו-pending); `_failure_reply(task_type="insurance")`.

## 3. מה נאסף מראש בשיחה מול מה שעולה כ-MISSING מרוכז

| מראש (תנאי ready) | עולה כ-MISSING מהדף |
|---|---|
| יעד (מדינה/אזור) | מיפוי יעד→אזור בדף אם לא חד-משמעי |
| תאריכי יציאה+חזרה (DD.MM) | ת"ז לכל נוסע (מזעור PII — רק כשמוכח שנדרש) |
| תאריך לידה לכל נוסע (DD.MM.YYYY; מספר הנוסעים נגזר) | שמות מלאים פר-נוסע כפי שהטופס דורש |
| הצהרת בריאות — שאלה מרוכזת אחת ⇒ `health_issues` | שאלת בריאות שנוסחה שונה מהותית (FIELD עם ציטוט) |
| הרחבות (שאלה אחת, ברירת מחדל: בלי) ⇒ `addons` | נקודת איסוף הכרטיס (OPTIONS מהדף) |
| שם/מייל (פרופיל), טלפון (וואטסאפ) | כל שדה שלא צפינו |

עיקרון: MISSING הוא רשת ביטחון, לא ערוץ האיסוף — שדה חוזר וצפוי מהריצות החיות
עובר לחבילת-מראש (עדכון `_EXTRACT`) בסבב ה-live-QA.

## 4. מפת אתר פספורטכארד — רכישת ביטוח נסיעות לחו"ל

(מקור: ‏WebFetch‏/‏WebSearch‏ בלבד, ללא דפדפן חי. תאריך: 2026-07-15)

### 4.1 דומיינים ונקודות כניסה (ודאות גבוהה)

- **פאנל הרכישה האמיתי:** `https://purchase.passportcard.co.il/` — תת-הדומיין
  הייעודי לרכישה אונליין. נתיב `/existing` = מסלול "לקוח קיים" (מי שכבר מחזיק
  כרטיס). זה ה-URL שהוזכר הכי הרבה בקישורי שותפים.
- **דומיין מקביל:** `https://buy.passportcard.co.il/` (גם `/existing`) — מופיע
  במקביל אצל סוכנים; כנראה אותה מערכת/גרסה.
- `https://www.passportcard.co.il/Purchase` — נקודת כניסה מהאתר הראשי שמפנה לפאנל.
- כל הקישורים החיצוניים שנמצאו נושאים `?AffiliateId=<base64>` — קישורי עמלה של
  סוכנים. **אנחנו נכנסים נקי, בלי affiliate.**

### 4.2 WAF (אומת היום)

`www.passportcard.co.il` ו-`purchase.passportcard.co.il` מחזירים **403** ל-WebFetch.
כל המפה נבנתה ממקורות צד-שלישי (אתרי סוכנים/השוואה). המשמעות לריצה:
`FAILED:blocked` קיים מהיום הראשון, וייתכן ש-Browserbase ייחסם גם הוא.

### 4.3 מבנה הטופס המשוער (ודאות בינונית — מקורות צד-שלישי בלבד)

1. **פרטי נסיעה:** "לאן נוסעים?" — בחירת אזור (אירופה, צפון אמריקה, דרום
   אמריקה, אסיה, אפריקה, אוקיאניה), תאריכי יציאה/חזרה, מספר נוסעים וגילאים
   ("להוספת נוסעים נוספים").
2. **הצהרת בריאות:** שאלון רפואי קצר (מחלות כרוניות, תרופות, אירועים רפואיים
   אחרונים); תשובה חיובית ⇒ שאלון מורחב, לעיתים הרחבה ייעודית + מסמכים רפואיים
   כתנאי לאישור — בדיוק הענף שהגארד שלנו מנתב ל-*9912.
3. **מסלול והרחבות:** בחירת תוכנית (מקור סוכן אחד: Basic/Classic/Premium) +
   הרחבות אופציונליות: סקי, ספורט אתגרי, הריון, אלקטרוניקה, ביטול נסיעה.
4. **גיל:** טבלת מחירים אצל סוכן מציינת החרפה מגיל 71+ עם "בדיקת חיתום" —
   מתיישב עם הגארד שלנו (85+ קשיח, בריאות חיובית ⇒ *9912; ‏71–84 יתברר חי).
5. **קבלת הכרטיס:** איסוף בנתב"ג או בנקודות חלוקה; כרטיס דיגיטלי באפליקציה;
   הפוליסה נכנסת לתוקף מיד עם הרכישה אונליין.
6. **ערוצים מקבילים:** רכישה גם טלפונית/דרך סוכן; המוקד = `*9912` — יעד ההפניה
   בכל הכישלונות הייחודיים.

מה שלא ידוע מהמקורות (סדר מסכים מדויק, פורמטי ולידציה, iframe תשלום) — בסעיף 7.

## 5. מה מומש

branch ‏`insurance-vertical`‏, 3 קומיטים מקומיים: ‏695ddea‏ → ‏ceb1309‏ →
‏b7b6e48‏; בלי ‏push‏, **אפס ריצות ‏Browserbase‏**. שער איכות ירוק
(‏ruff‏ + ‏209 pytest‏, 15.07).

**קבצים:**

- `app/automation/bu_runner.py` — בלוקים משותפים
  (`_NAV_GENERIC`/`_PERK_BLOCK`/`_DRY_TAIL`/`_COMMIT_TAIL`, מילה-במילה
  מ-‏152cb80‏) + dispatch על `task_type`; `_build_insurance_task` מלא;
  `_parse_result`: ‏`missing_fields`‏ (cap 12, `missing`=הראשון),
  ‏`FIELD`‏/‏`OPTIONS <key>`‏ ממופתחים + גישור לשדה-בודד, ‏`extra`‏ (מעוגן
  לשורת ה-‏SUMMARY_REACHED‏ בתוך 3 השורות האחרונות — לא ל-‏last‏ המשולש, כי
  שורות בלוק-הסיום מודבקות שם; חיתוך markers שהודבקו, cap 120).
- `app/automation/resolve.py` — `INSURANCE_URL` קבוע + `resolve_insurance_url()`
  (תמיד `one`, בלי ‏Brave‏); `_pick` המשותף מהקולנוע (שקול התנהגותית למסעדות).
- `app/automation/browser_book.py` — `BU_INSURANCE_TIMEOUT_S=1200` +
  `_timeout_s(job)`, `max_steps=80`, פרמטרי `task_type`/`insurance`/
  `form_answers`, ‏passthrough‏ של שדות הפרוטוקול ל-`details`.
- `app/pipeline.py` — `_SCHEMA`/`_EXTRACT` עם `task_type=insurance` וחבילת
  השדות + ערוץ `answers`; גארדים לפני ריצה (בריאות חיובית / גיל 85+ ⇒ *9912,
  יעד ריק ⇒ שאלה); `_multi_ask` אחת לכל העצירה; `_truth_note` עם `remaining`;
  השלמה דטרמיניסטית ב-`handle_inbound` ⇒ `run_booking` עם `form_answers`;
  הודעות quote (קיר-כרטיס פרמיה + ‏pending‏ "להמשיך לתשלום?");
  `_failure_reply(task_type="insurance")` ⇒ *9912; ‏PII‏ — `form_answers` חיים
  רק ב-flow הרץ.
- `tests/test_multi_missing.py` + `tests/test_insurance.py` — ‏774‏ שורות
  (פירוט בסעיף 6); `poc/spike_insurance.py` — נכתב, **לא הורץ**.

## 6. טסטים וספייק

- `tests/test_multi_missing.py` — פרסור הפרוטוקול, תאימות לאחור, חיתוך ערבוב
  markers, `_multi_ask`, מיזוג `answers` חלקי/מלא, הישרדות `_save_flow`.
- `tests/test_insurance.py` — חוזה ה-resolve, ה-task, timeout/max_steps, `extra`
  עד details, גארדים (mock שנכשל אם ‏book‏ נקרא), `_failure_reply` (עוגן
  `*9912`), הודעות quote עוברות `character_leaks`, הסכמה.
- `poc/spike_insurance.py` — DRY_RUN קשיח, release_session ב-finally. **סבבי
  ה-live יתחילו ממנו בלבד**; חיווט ה-pipeline נכנס לשימוש רק אחרי עצירה כנה
  מלאה (CARD_REQUIRED/MISSING) בספייק.

שער איכות: `ruff check . && ruff format --check . && pytest -q`.

## 7. מה מחכה לשלב הריצות החיות

**טריגר:** הסבב יושגר רק כשהטסט החי הנוכחי (בטא מסעדות) מסתיים — לא במקביל.
**סדר:** `poc/spike_insurance.py` ב-DRY_RUN בלבד ⇒ עצירה כנה
(CARD_REQUIRED/MISSING/פרמיה ב-`extra`) ⇒ רק אז מדליקים את מסלול ה-pipeline.

מה יתברר רק חי (לא לנחש בקוד):

1. **WAF** — האתר מחזיר 403 ל-WebFetch; ייתכן ש-Browserbase ייחסם ⇒
   `FAILED:blocked` קיים מהיום הראשון, ובודקים סטטוס Browserbase לפני שחופרים
   בקוד.
2. סדר המסכים והפיצול חדש/`/existing` (ואיזה דומיין באמת עונה — `purchase` או
   `buy`).
3. אילו שדות פר-נוסע באמת, פורמט תאריכים ולידציות.
4. הצהרת בריאות פר-נוסע או פעם אחת; היכן עובר קו ה-71+.
5. מסך תשלום: iframe/3DS.

רמזי ניווט שיתגלו חיים נכנסים ל-task כשורות עקרון; שדות MISSING חוזרים עוברים
לחבילת-מראש (עדכון `_EXTRACT`) בסבב ה-live-QA.
