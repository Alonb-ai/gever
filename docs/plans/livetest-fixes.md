# תוכנית תיקון — באגים מהריצה החיה הראשונה (2026-06-25)

הריצה החיה הראשונה דרך WhatsApp ("רוטשילד ל-4 ב-20:00") חשפה 6 באגים. כולם מקורקעים
בקוד למטה. **עיקרון-על מנחה:** כשגבר לא יודע משהו — אסור לו להחליט לבד, הוא חוזר ללקוח
לברר. לעולם לא להמציא נתון, לעולם לא לנחש מסעדה.

## מה קרה בריצה
ביקשנו רוטשילד → גבר סגר **רוסטיקו בזל** (מסעדה אחרת), ב-dry-run, עם **מייל מומצא**
(`alon@example.com`) ו**שם משפחה מומצא**, ירה **פעמיים**, ולא יידע שנסגר.

---

## הבאגים והתיקונים (כל שינוי כירורגי, ממופה לבאג)

### באג 1 🔴 — recon סוגר הזמנה אמיתית במקום בלי-כרטיס
`bu_runner._build_task` ב-dry_run אומר "עצור בשלב הכרטיס". רוסטיקו לא דורש כרטיס → אין
איפה לעצור → ה-agent המשיך ולחץ "סיום" וסגר באמת.
**תיקון — `app/automation/bu_runner.py`:**
- ב-recon (dry_run): לעצור ב**מסך הסיכום**, *לפני* כפתור האישור הסופי (סיום/אשר/הזמן/תשלום),
  בלי קשר אם יש כרטיס. **לעולם לא ללחוץ** על הכפתור הסופי. לדווח marker `SUMMARY_REACHED`
  + האם נדרש כרטיס (`CARD_REQUIRED`).
- `_parse_result`: recon `success` = הגיע לסיכום (`SUMMARY_REACHED`), `booked=False` תמיד.

### באג 2 🔴 — מסעדה שגויה (resolve מנחש)
`resolve_ontopo_url` שורות 69-70: כשאין match חזק → מחזיר את התוצאה הראשונה כ-`one`.
**תיקון — `app/automation/resolve.py`:**
- למחוק את ברירת-המחדל "תוצאה ראשונה". כשאין match חזק → להחזיר `many` (עם המועמדים
  לשאלת הבהרה) או `none` אם אין כלום סביר. **לעולם לא לבחור לבד.** (מחיקה, לא הוספה.)

### באג 3 🔴 — המצאת פרטי לקוח (מייל + שם משפחה)
ה-agent קיבל מייל ריק והמציא `alon@example.com`, וגם המציא שם משפחה לשדה חובה.
**תיקון בשתי שכבות:**
- `bu_runner._build_task` (שני המצבים): "השתמש **רק** בשם/מייל/טלפון שבדיוק ניתנו ב-job.
  **אסור להמציא או לנחש שום ערך.** אם שדה חובה ריק — אל תמלא, עצור ודווח `MISSING:<שדה>`."
  להסיר את ברירת-המחדל `or "אלון"` מה-task (לא להזריק שם מזויף).
- `_parse_result`: אם דווח `MISSING:<field>` → `success=False` + השדה החסר ב-details.
- `app/pipeline.py`: **מנגנון אחד** — לא לבדוק שדות מראש (לא יודעים מה Ontopo דורש). מעבירים
  את מה שיש (בלי defaults/placeholder); כש-recon מחזיר `MISSING:<field>` → גבר מבקש מהלקוח
  את השדה וממתין (reuse של דפוס ה-ask הקיים של none/ambiguous), ואז recon חוזר.
  **ponytail: הטופס מחליט מה חובה, לא אנחנו — אין רשימת-שדות כפולה לתחזק.**

### באג 4 🔴 — ירי כפול (double-fire)
"?" של הלקוח גרם למודל לירות `ready=true` שוב → `run_booking` שני במקביל, התנגש בראשון.
**תיקון — `app/pipeline.py` (`handle_inbound`):**
- guard: לא לירות `run_booking` אם כבר יש הזמנה בתהליך לטלפון הזה (`_booking[phone].state == "working"`).

### באג 5 🟠 — "רגע אני על זה 🔄" חוזר כל תור
**תיקון — `app/pipeline.py`:** ה-notify נשלח פעם אחת לכל הזמנה (ה-guard של באג 4 מסיר את
הכפילות; לוודא שאין notify חוזר בכניסה-חוזרת).

### באג 6 🟠 — card_required false-positive
`_parse_result` ב-recon: `"כרטיס" in final` תופס גם שלילה ("לא נדרש כרטיס") → דגל שגוי.
**תיקון — `app/automation/bu_runner.py`:** לזהות כרטיס רק לפי marker מפורש `CARD_REQUIRED`,
לזרוק את היוריסטיקת ה-substring העברית.

### עיקרון-על 🔴 — "כשלא יודע, שואל" (persona)
**תיקון — `app/llm/intent.py` (`SYSTEM_PROMPT`):** חוק קצר — גבר לעולם לא ממציא פרטים על
הלקוח/המשימה, וכשמשהו לא ברור או לא ידוע (איזו מסעדה, פרט חסר) הוא **שואל**, לא מנחש.
תואם-דמות (סוגר-עניינים אמיתי מוודא "איזה רוטשילד?" לפני שזז).

### last-verify (משלים את הזרימה)
אחרי ש-recon מגיע לסיכום (`pending`), הודעת גבר חייבת **לנקוב בשם המסעדה שנפתרה** כדי
שהלקוח יתפוס מסעדה שגויה: "מצאתי שולחן ב<רוסטיקו בזל> ל-4 ב-20:00 — לסגור?".
**תיקון — `app/pipeline.py`:** `_pending` info כולל את שם המסעדה; truth_note ל-`pending`
מורה לפרסונה לנקוב בשם ולבקש אישור.

---

## חוזה ה-recon (markers — מקור אמת אחד ל-bu_runner ↔ pipeline)
ה-agent מסיים את הדיווח באחד מאלה (recon):
- `SUMMARY_REACHED` — הגיע למסך הסיכום ועצר (הצלחה). מצורף `CARD_REQUIRED` אם נדרש כרטיס.
- `MISSING:<field>` — שדה חובה ריק, לא מילא (גבר ישאל את הלקוח).
ב-commit (קיים): `BOOKED <conf>` / `CARD_REQUIRED`. אין fabרication באף מצב.

## בדיקות (ponytail: בדיקה אחת לכל לוגיקה לא-טריוויאלית)
- `resolve`: no-strong-match → `many`/`none`, אף פעם לא `one` שרירותי.
- `_parse_result`: `SUMMARY_REACHED`→success+not-booked; `MISSING:email`→fail+field; `CARD_REQUIRED` רק לפי marker (שלילה עברית לא מדליקה).
- `pipeline`: double-fire guard (הזמנה שנייה בזמן `working` לא יורה); חסר-מייל→שואל-לא-מזמין.

## קבצים
`app/automation/resolve.py` · `app/automation/bu_runner.py` · `app/pipeline.py` ·
`app/llm/intent.py` · `tests/test_resolve.py` · `tests/test_bu_runner.py` · `tests/test_realbooking.py`
