# Plan — multi-platform resolve (Ontopo › Tabit › אתר המסעדה)

## הרקע (מ-dry-run 3)
לקוח ביקש "גרקו ביץ' פרישמן". המסעדה **לא קיימת ב-Ontopo** (resolve החזיר דף אירוע
שפג, `ontopo.com/page/37007370`), אבל **כן קיימת ב-Tabit**
(`tabitisrael.co.il/online-reservations/create-reservation?...&orgId=5a005ba1b697f322003f3020`).
גבר נכשל בצדק על Ontopo — אבל היה צריך להמשיך ל-Tabit ולסגור שם.

**המטרה:** resolve יחפש את המסעדה בכמה פלטפורמות ויתעדף **Ontopo › Tabit › אתר המסעדה**.

## בוצע עד כה (לא קומיט — ממתין לאישור)
- **`bu_runner._build_task` → עקרוני, לא דטרמיניסטי + platform-agnostic.** הוסר המתכון
  הממוספר הנעול ל-Ontopo ושם הכפתור "מצאו לי שולחן". עכשיו: מטרה + עקרונות + חוקי ברזל,
  וה-agent מבין כל UI לבד (Ontopo/Tabit/אחר). ה-markers ללא שינוי. + טסט guard.
- **`browser_book._cdp_url()` מומש** (היה stub): יוצר סשן Browserbase
  (`POST /v1/sessions`, `solveCaptchas` דלוק כברירת-מחדל + `proxies:true`) ומחזיר connectUrl.
  צד ה-runner כבר תמך ב-cdp_url. **נותר:** להפוך `BU_BROWSER=browserbase` ב-.env ולהריץ
  (עולה כסף per session — לכן בנפרד, באישור). זה פותר את חסימת ה-CAPTCHA שראינו ב-local Chrome.

## מצב נוכחי (האילוץ)
- `resolve.py` — חיפוש DDG-HTML של `"<name> ontopo"`, regex רק ל-`ontopo.com/.../page/\d+`,
  דיסאמביגואציה לפי כותרת, מחזיר url. **נעול ל-Ontopo**.
- `pipeline.run_booking` → `resolve_ontopo_url(name)` → `book_table_bu(page_url=...)`.
- `bu_runner._build_task` — prompt **ספציפי ל-Ontopo** (שורה "אתר Ontopo" + שלב "מצאו לי שולחן").
- ה-markers (`SUMMARY_REACHED`/`CARD_REQUIRED`/`BOOKED`/`MISSING`) — **פלטפורמה-אגנוסטיים** ✓.
- שלד ה-task גנרי (סועדים→תאריך→שעה→מצא שולחן→סיכום→פרטים→עצור) — קל להכללה.

## החלטות עיצוב
1. **החיפוש נשאר בצד-שרת** (`resolve.py`, DDG-HTML) — *לא* נותנים ל-agent לגגל בעצמו:
   browser-use נחסם ב-CAPTCHA בגוגל/בינג/DDG (נצפה ב-dry-run 3). resolve בלי דפדפן עוקף את זה.
2. **שאילתה:** `"<name> הזמנת מקום"` במקום `"<name> ontopo"` — רחב, תופס את שתי הפלטפורמות.
3. **תיעדוף:** Ontopo › Tabit. שתיהן קיימות → Ontopo. רק Tabit → Tabit.
4. **מבנה החזרה:** מוסיפים `platform` → `{status, url, platform, candidates}`.
5. **task גנרי:** מסירים את ה-hardcoding ל-Ontopo ואת הכפתור "מצאו לי שולחן"; ניסוח גנרי
   ("אתר הזמנות מסעדה") + רמיזת platform. ה-agent אוטונומי, מסתדר עם UI שונה.
6. **fallback לאתר המסעדה — נדחה.** כל אתר שונה, אין flow גנרי, זיהוי dry-run קשה. Roadmap.

## סיכונים / לא-ידועים (לדה-ריסק לפני קוד)
- ~~**צורת ה-URL של Tabit:** האם DDG מאנדקס deep-link של Tabit?~~ **נבדק ✓ (Phase 0):**
  DDG מאנדקס Tabit בצורה נקייה `tabitisrael.co.il/site/<שם-מסעדה>` (לא ה-orgId deep-link).
  לשאילתה `"<name> הזמנת מקום"` חוזרים גם Ontopo וגם Tabit → התיעדוף ישים. ה-regex פשוט:
  `tabitisrael\.co\.il/site/`. **נותר:** האם דף ה-`/site/` מוביל ל-flow עם מסך סיכום
  לפני תשלום (ספייק browser-use, Phase 0-ב').
- **flow ההזמנה של Tabit** שונה מ-Ontopo (`step=search` → בחירת slot → פרטים). ה-task הגנרי
  חייב לכסות. צריך live test על Tabit (כמו ספייק ה-Ontopo המקורי).
- **נקודת עצירה ל-dry-run ב-Tabit:** האם יש מסך סיכום ברור *לפני* תשלום/אישור? לוודא.
- `_is_listing`/`_match_restaurant` ב-`ontopo.py` — בעצם string-match גנרי, אמורים להחזיק.

## תוכנית מדורגת
### Phase 0 — ספייק/recon (לפני קוד)
- להריץ את חיפוש ה-DDG של resolve על 2-3 מסעדות שב-Tabit (גרקו + עוד), ולבדוק אילו URLs
  חוזרים ובאיזו צורה. **לוודא ש-Tabit findable** — אחרת כל התוכנית משתנה.
- ספייק browser-use קצר על flow של Tabit (גרקו) עד מסך הסיכום — לתעד שמות כפתורים ואת
  נקודת ה"עצור לפני אישור". מראה כמו ספייק ה-Ontopo המקורי ב-`poc/`.

### Phase 1 — `resolve.py` multi-platform
- regex מוכלל ל-ontopo + tabit (לוכד platform). שאילתה `"<name> הזמנת מקום"`.
- תיעדוף ontopo › tabit; שמירת סינון listing + לוגיקת match. החזרת `platform`.
- שינוי שם `resolve_ontopo_url` → `resolve_reservation_url` (+ עדכון callers).
- טסטים: fixtures של DDG HTML עם לינקים משתי הפלטפורמות → priority + platform + none/many.

### Phase 2 — `bu_runner._build_task` גנרי
- "אתר Ontopo" → "אתר הזמנות מסעדה (<platform>)"; שלב 4 "מצאו לי שולחן" → "הצג/מצא
  שולחנות פנויים". שמירת כל ה-markers + חוקי הברזל.
- העברת `platform` ב-job (`browser_book` → `bu_runner`).
- טסט: בונה task בלי "Ontopo"/"מצאו לי שולחן" hardcoded; markers קיימים.

### Phase 3 — חיווט + live test
- pipeline מעביר platform. dry-run חי על גרקו דרך Tabit → צפוי `SUMMARY_REACHED`.
- regression חי על מסעדת Ontopo → עדיין עובד.

### Phase 4 (אחר כך) — fallback לאתר המסעדה
מחוץ ל-scope עכשיו. Roadmap.

## בדיקות
- **Unit:** resolve fixtures (ontopo-only / tabit-only / both→ontopo / neither→none-many);
  task-builder (אין "Ontopo"/"מצאו לי שולחן" קשיח; markers קיימים).
- **Live:** גרקו/Tabit dry-run; regression על Ontopo.
