# Retro — Dry-run #1 (הריצה החיה הראשונה ב-WhatsApp, 2026-06-25)

הריצה החיה הראשונה מקצה-לקצה: הודעת WhatsApp אמיתית → שיחת פרסונה → browser-use נוהג
ב-Ontopo. **התוצאה: הניווט עבד יפה, אבל חשפנו 6 באגים — חלקם בטיחותיים.** המסמך הזה
מאגד מה גילינו, איך תיקנו, ואיפה לדקור אם זה חוזר.

## מה קרה בקצרה
ביקשנו **"רוטשילד" ל-4 ב-20:00**. גבר:
1. סגר **רוסטיקו בזל** (מסעדה אחרת לגמרי) — resolve ניחש במקום לשאול.
2. עשה **הזמנה אמיתית למרות dry-run** — רוסטיקו בלי-כרטיס, ושער ה-recon ("עצור בכרטיס")
   לא היה לו כרטיס לעצור בו, אז המשיך עד "הזמנתך התקבלה בהצלחה".
3. **המציא מייל** (`alon@example.com`) ושם משפחה — שדות חובה ריקים שה-agent מילא לבד.
4. **ירה פעמיים** — ה-"?" של הלקוח גרם ל-ready=true שוב.

## הבאגים, התיקון, וה-marker לזיהוי חוזר

| # | סימפטום | שורש | תיקון (commit 61ec677) |
|---|---------|------|------------------------|
| 1 | dry-run עשה הזמנה אמיתית | recon "עוצר בכרטיס", אבל מקום בלי-כרטיס → אין איפה לעצור | recon עוצר ב**מסך הסיכום** לפני האישור הסופי, תמיד (`SUMMARY_REACHED`) |
| 2 | מסעדה שגויה | `resolve` החזיר תוצאה ראשונה כשאין match חזק | אין match → `many`/`none`, גבר שואל. אף פעם לא בוחר לבד |
| 3 | מייל/שם מומצאים | שדה חובה ריק → ה-agent ממלא לבד | איסור המצאה ב-bu_runner; שדה ריק → `MISSING:<field>`, גבר מבקש מהלקוח |
| 4 | ירי כפול | "?" → ready=true שוב → run_booking שני | guard: `state=="working"` חוסם, נקבע סינכרונית לפני spawn (TOCTOU) |
| 5 | "רגע אני על זה" חוזר | אין guard לכניסה-חוזרת | אותו guard של #4 |
| 6 | card_required שגוי | substring "כרטיס" תפס שלילה ("לא נדרש כרטיס") | רק marker מפורש `CARD_REQUIRED` |

עיקרון-על שנגזר: **כשגבר לא יודע — שואל, לא מחליט. ולעולם לא ממציא נתוני לקוח.** (ב-persona).

## Diagnostic playbook — אם זה חוזר, דקור פה קודם

- **גבר לא עונה ב-WhatsApp** → כמעט תמיד ה-Callback URL ב-Meta מצביע ל-tunnel מת
  (localhost.run נותן subdomain אקראי בכל reconnect). הטוקן כמעט אף פעם לא האשם.
  בדוק לפי הסדר: `curl localhost:8000/health` → `curl <registered-url>/health`
  (אם "no tunnel here" → לעדכן URL נוכחי ב-Meta) → רק אז הטוקן.
  הרץ tunnel עם `... localhost.run 2>&1 | tee ~/gever_tunnel.log` כדי תמיד לקרוא את ה-URL.
- **"לא נשמר ל-Supabase"** → Supabase **כן** מחובר (גם מקומית). recon (dry-run) **לא**
  קורא ל-`log_booking` — רק `run_commit` רושם הזמנה. name/email בפרופיל null עד שה-onboarding
  הייעודי יאסוף אותם. שתי סביבות: `.env` מקומי (השרת המקומי) מול Coolify (prod) — נפרדות.
- **הזמנה אמיתית "בטעות"** → ודא שזה לא commit (`settings.dry_run=False` + "מאשר"). recon
  לא אמור לסגור; אם סגר → בדוק את שער הסיכום ב-`bu_runner._build_task`.
- **שני venv** → ה-app על python3.14/google-genai 2.8; browser-use ב-`.venv-bu`
  (python3.12, google-genai 1.65). ה-subprocess מקבל את מפתח Gemini ב-`env=`.

## ההקלטות
כל ריצה מתועדת ב-`bu_recordings/<run_id>/`: `run.gif` (ויזואלי), `conversation/` (הנמקת
ה-agent צעד-צעד), `result_<id>.json` (התוצאה). **אם אין `result.json` → ה-subprocess
נהרג לפני סיום (timeout/קריסה).**
