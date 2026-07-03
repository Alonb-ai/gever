# Plan — pause-resume אמיתי (הפינג-פונג): עצירה→שאלה→המשך מאותו מסך

> מבוסס מחקר מאומת (2026-07-03): קוד browser-use 0.13.1 המותקן + docs.browserbase.com.
> הבעיה: MISSING מסיים את הריצה; תשובת הלקוח מפעילה ריצה חדשה מאפס (~3-4 דק').
> היעד: הסשן נשאר חי בזמן שגבר שואל, וההמשך הוא מאותו מסך — שניות במקום דקות.

## הארכיטקטורה הנבחרת: keepAlive + חיבור מחדש (subprocess טרי)

הדפדפן (Browserbase) שומר את המסך בדיוק איפה שנעצר; ה-runner מת ונולד מחדש —
ה-state האמיתי (טופס מלא, slot נבחר) חי בדפדפן, לא ב-agent.

1. **`_cdp_url()`** (browser_book.py): להוסיף ל-body של יצירת session:
   `"keepAlive": true, "timeout": 1800` (30 דק'), ולהחזיר גם `session_id`.
2. **על `MISSING:*`**: לא משחררים את הסשן; שומרים ב-`_booking[phone]`:
   `session_id`, `connectUrl`, והדיווח האחרון של ה-runner (ה-recap).
3. **כשהלקוח עונה**: `GET /v1/sessions/{id}` — אם `status=="RUNNING"`:
   subprocess חדש עם אותו `cdp_url` + job עם `resume:true` שבונה task
   "אתה באמצע הזמנה, המסך פתוח בדיוק איפה שעצרת, הלקוח ענה: <תשובה> — המשך".
   ⚠️ בלי ה-URL המקורי ב-task + `directly_open_url=False` ב-Agent — אחרת
   browser-use מנווט מחדש והורס את המסך (ברירת מחדל True!).
4. **fallback חלק**: סשן `TIMED_OUT/COMPLETED/ERROR` או שה-resume נכשל →
   הריצה-מחדש הקיימת עם התשובה ב-notes (כבר בנוי). ההבדל ללקוח: זמן בלבד.
5. **שחרור חובה**: `POST /v1/sessions/{id}` עם `{"status":"REQUEST_RELEASE"}`
   על כל תוצאה סופית (BOOKED/FAILED/card/resume מוצלח) — keepAlive מחייב
   דקות-דפדפן גם באידל עד ה-timeout. עלות תרחיש נטוש: ~0.5 שעת דפדפן.

## למה לא החלופות

- **subprocess חי עם stdin ping-pong** (add_new_task של browser-use): שומר זיכרון
  agent מלא אבל הופך את ה-runner לדמון (פרוטוקול stdin, ניתוח BU_TIMEOUT_S,
  שביר ל-restart), ויש היסטוריית באגים ב-CDP אחרי אידל של דקות (issue #3069).
  ה-recap ב-task מחליף את זיכרון הצעדים מספיק טוב.
- **Agent.pause()/resume()**: מנגנון חיצוני (Ctrl+C), לא זמין ל-agent עצמו כשהוא
  מזהה שחסר לו נתון. לא מתאים.
- **ask-human custom action חוסם**: step_timeout=180s ברירת מחדל — תשובת וואטסאפ
  של דקות/שעות מפוצצת אותו.

## עובדות מאומתות (מהקוד/docs)

- browser-use לא סוגר סשן Browserbase לעולם (רק מנתק CDP) — הבעלות על החיים
  של הסשן היא שלנו דרך ה-API.
- Browserbase: reconnect לאותו `connectUrl`, סטטוס ב-`GET /v1/sessions/{id}`,
  timeout מקס 6 שעות. keepAlive זמין בתוכניות בתשלום (Developer $20 = בתשלום;
  אישוש פר-tier מדויק — בזמן המימוש).
- Developer plan: 25 סשנים במקביל — סשנים ממתינים אוכלים מהמכסה.

## מדרגות (משלימות, כבר קיימות)

- ✅ דיווח כן בסוף ריצה (FAILED:no_availability → "אין זמינות במועד").
- ✅ notes: תשובת הלקוח מגיעה לריצה החוזרת (ה-fallback של התוכנית הזאת).
- ⬜ המימוש כאן (המדרגה השלישית) — אחרי שהבטא רצה יציב על ה-fallback.
- ⬜ (אופציונלי, נפרד) עדכוני סטטוס תוך-ריצה דרך callbacks של browser-use.
