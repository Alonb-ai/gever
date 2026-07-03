> ⚠️ **סטטוס היסטורי (2026-06-19)** — קדם את המעבר ל-browser-use ואת ה-deploy.
> המצב העדכני: `docs/plans/beta-roadmap.md`. נשמר כתיעוד בלבד.

# גבר / Gever — Beta-Readiness Gap Report

> סטטוס נכון ל-2026-06-19. מבוסס קריאת קוד + git log + אימות חי של Supabase.
> כל הטענות מעוגנות בקובץ או קומיט. **Supabase חוּבּר ואומת חי בסשן הזה** (טבלאות
> `users`/`bookings` מחזירות HTTP 200 עם service key, anon מקבל 401 → RLS אכוף).

---

## 1. סטטוס לפי זרוע (זרועות מ-`roadmap.md`)

| זרוע | תחום | סטטוס | ראיה |
|---|---|---|---|
| **1** | ביצוע — Browserbase + Stagehand | 🟡 **בתהליך** | PoC ירוק ב-DRY_RUN; מנוע `act_verified` קיים (`app/automation/engine.py`); אך **בחירת תאריך עדיין לא נתפסת בווידג'ט** ואין מסלול הזמנה אמיתית. קומיטים `c52f404`, `cd1c8e3`, `9b32171` |
| **2** | מוח ושיחה — Gemini + persona | 🟡 **בתהליך** | פרסונה כדמות + `character_leaks` ב-`app/llm/intent.py`; חילוץ שדות עובד inline ב-`pipeline.py` (`_EXTRACT`/`_SCHEMA`). אך `understand()`→`Intent` מובנה וזיהוי action (insurance/tickets) טרם נכתבו. קומיטים `f9f535d`, `031c524` |
| **3** | ערוץ — WhatsApp (Meta Cloud API) | 🟡 **בתהליך** | לופ חי מקצה-לקצה (`app/main.py` + `app/whatsapp/client.py`); אימות חתימה `X-Hub-Signature-256` קיים אך gated (`fe07ea6`). **חסר: System User token קבוע** (Temporary פג ~24ש') ו-host יציב |
| **4** | Backend — FastAPI + Supabase | 🟢 **בוצע (הודלק חי)** | `app/db/memory.py` + `schema.sql`; **אומת חי**: טבלאות `users`/`bookings` קיימות, RLS אכוף, מפתחות ב-`.env`. קומיט `45c748c`, פרויקט `eebnppyxovneznbkhgax` |
| **5** | תשתית — Docker / Coolify | 🔴 **לא התחיל (פרודקשן)** | `Dockerfile` + `.dockerignore` קיימים ובר-התקנה; אך **deploy ל-Coolify לא בוצע** — עדיין localhost + tunnel זמני (`lhr.life`). `roadmap.md` זרוע 5 |
| **6** | תשלום — Lemon Squeezy | 🔴 **לא התחיל** | **אפס קוד**. `grep lemon app/` → רק הערת ponytail ב-`config.py:35` ("שדות עדיין מוסרים"). מפתחות ב-`.env` ריקים |
| **7** | שיווק — GTM | 🟡 **חלקי** | דף נחיתה HTML מלא (`web/index.html`, `30cd697`) + ערכת GTM (`docs/marketing/`); אך **7 placeholders של `WHATSAPP_NUMBER`/`wa.me/WHATSAPP`** עדיין בקוד, social-proof מזויף, אין חיבור וייטליסט אמיתי |

---

## 2. מוקד נוכחי

לפי `CLAUDE.md` ("Current focus") + 10 הקומיטים האחרונים:

**זרוע 1 — אמינות הביצוע** היא הלב הפעיל. הקומיטים האחרונים (`c52f404`, `cd1c8e3`)
עוסקים כולם במנוע `act→verify→self-heal` ובתיקון בחירת התאריך (ממצאי חקירת Stagehand:
`backend_node_id` + `dom_settle` ב-start). במקביל: פרסונה (`f9f535d`), דיווח שגיאות
מפורט ל-WhatsApp (`629ebbb`), ושיווק/landing. ה-`MORNING_REVIEW.md` מצהיר במפורש:
"**זרוע 1 (אמינות Browserbase) — הסיכון מס' 1**" שדורש לולאת dry-run אינטראקטיבית.

המעבר המוצהר הוא **שלב 1→2**: הזמנה אמיתית מעבר ל-DRY_RUN + ייצוב (token קבוע + Coolify).

---

## 3. זרועות ללא שום מימוש

- **זרוע 6 (Lemon Squeezy)** — אפס קוד. רק הערת ponytail ושדות `.env` ריקים. לבטא סגור
  של 2-3 חברים זה **תקין ולא חוסם** (אין צורך לגבות תשלום בבטא).
- **זרוע 5 (Coolify deploy)** — תשתית Docker קיימת, אבל ה-deploy עצמו לא קרה אף פעם.
  זה **כן חוסם בטא** (ראה למטה — בלי host יציב, גבר מפסיק לענות תוך ~24ש').

שאר הזרועות (1,2,3,4,7) כולן עם מימוש משמעותי.

---

## 4. רשימת פערים לבטא (2-3 משתמשים אמיתיים)

מה *חייב* לעבוד מקצה-לקצה כדי שחבר ישלח הודעה ויקבל הזמנת מסעדה אמיתית:

| רכיב | סטטוס | הראיה | הפעולה החשובה הבאה |
|---|---|---|---|
| **לופ WhatsApp** | 🟢 ready | `main.py` webhook → `pipeline.handle_inbound` → `send_text`; אומת חי ביוני | אין — עובד. רק לוודא שורד redeploy |
| **הזמנה אמיתית (מעבר ל-DRY_RUN)** | 🔴 **missing** | `pipeline.run_booking` קורא ל-`book_table(..., dry_run=True)` קשיח (`pipeline.py:209`); המסלול ה-`else` ב-`ontopo.py:275` (`אשר את ההזמנה סופית` + login/OTP) **לא נבדק מעולם** | בנה+בדוק את מסלול ה-`dry_run=False`: login/OTP/טלפון + לחיצת אישור סופי. זה החסם מס' 1 |
| **אמינות בחירת תאריך** | 🔴 **risky** | באג פתוח מתועד ב-`MORNING_REVIEW.md` §3 + `roadmap.md` ("התאריך לא נתפס בווידג'ט"); `act_verified` קיים אבל הבעיה לא נפתרה | לולאת dry-run חיה לפי הדפוסים ב-`docs/research/findings.md` (scroll-into-view, observe→act, extract-verify). `verify-before-commit` כבר מונע סגירה שקטה על תאריך שגוי |
| **פרסונה** | 🟢 ready | `SYSTEM_PROMPT` כדמות + `character_leaks` + `gender_line` ב-`intent.py`; חוק "לא לזייף סטטוס" אכוף דרך `_truth_note` ב-`pipeline.py` | אין — מוכן. כדאי לשפוט חי אחרי redeploy |
| **זיכרון (Supabase)** | 🟢 **ready (הודלק חי)** | `memory.py` מחובר ב-`pipeline._seed_instruction`/`run_booking`; טבלאות אומתו חי, RLS אכוף, PII מוצפן Fernet | אין — חי. רק לוודא ש-`ENCRYPTION_KEY` יציב (החלפתו תהפוך PII ישן ללא-קריא; `_decrypt` מחזיר ciphertext as-is) |
| **דיווח שגיאות** | 🟡 partial | `engine.error_detail` שולח type+session ל-WhatsApp, **אבל gated ב-`debug_errors`** (`config.py:33`, default True). מתאים לבטא; חובה לכבות לפני קהל | להשאיר `DEBUG_ERRORS=True` לבטא (3 חברים → מועיל); להוסיף לוג מובנה מרכזי (P1-6 במחקר) |
| **deploy פרודקשן (Coolify + tunnel)** | 🔴 **missing — חסם המשכיות** | עדיין localhost + `lhr.life` (`roadmap.md` זרוע 5); ה-tunnel מתנתק → Callback URL מתיישן | deploy ל-Coolify (app מה-repo, env ב-UI, subdomain+SSL); ואז Callback URL קבוע ב-Meta |
| **System User token** | 🔴 **missing — חסם המשכיות** | Temporary token פג ~24ש' (`roadmap.md` זרוע 3) → גבר מפסיק לענות | להחליף ל-Meta System User token קבוע. **בלי זה הבטא מת תוך יום** |
| **landing/waitlist** | 🟡 partial | `web/index.html` קיים אבל **7 placeholders `WHATSAPP_NUMBER`** (שורות 12,335-336,604-605,624-625) + social-proof מזויף; וייטליסט לא מחובר | לבטא של 3 חברים — **לא חוסם** (שולחים לינק ישיר). להחליף מספר + להעלות רק לפני launch ציבורי |

---

## 5. חמש פעולות מתועדפות להגעה לבטא

1. **בנה ובדוק את מסלול ההזמנה האמיתי (`dry_run=False`).**
   המסלול ב-`ontopo.py:275` (`אשר את ההזמנה סופית` + מילוי שם/טלפון + טיפול ב-login/OTP)
   לא הורץ מעולם. זה הפער שהופך "הגיע למסך אישור" ל"באמת הזמין". **חסם הליבה.**

2. **תקן את אמינות בחירת התאריך בלולאת dry-run חיה.**
   הבאג הגדול הפתוח. הדפוסים מוכנים ב-`docs/research/findings.md` (P0-1..P0-5):
   scroll-into-view + observe→act + extract-verify. `verify-before-commit` כבר מבטיח
   שגבר לא ייסגר בשקט על תאריך שגוי — אבל הוא עדיין נכשל לבחור אותו.

3. **deploy ל-Coolify + System User token קבוע.**
   שני אלה ביחד = המשכיות. בלעדיהם גבר מפסיק לענות תוך ~24ש' (token) או כשה-tunnel
   נופל (host). זה ההבדל בין "הדגמתי לחבר פעם אחת" ל"בטא שרץ שבוע".

4. **ודא את זיכרון Supabase חי end-to-end דרך WhatsApp.**
   החיבור והטבלאות אומתו, אבל לא נבדק שהזמנה אמיתית כותבת ל-`bookings` ושה-recap
   חוזר בשיחה הבאה. שלח שתי הזמנות מאותו מספר וודא ש-"בפעם הקודמת..." מופיע.
   קבע `ENCRYPTION_KEY` סופי **לפני** שמשתמשים אמיתיים נכנסים (החלפה = PII ישן אבוד).

5. **החלף מספר WhatsApp ב-landing + שפוט פרסונה חי.**
   7 ה-placeholders ב-`web/index.html` + שפיטת הפרסונה החדשה (`031c524`/`f9f535d`)
   אחרי ה-redeploy: (א) "סגרת?" → לא מזייף סטטוס, (ב) "טאיזו" → בוחר אחד.
   הקלה ביחס ל-1-4, אבל מהירה וחוסמת launch ציבורי.

---

### הערות חתך

- **זרוע 6 (תשלום) לא חוסמת בטא סגור** — דלג עליה עד שמוכיחים שהליבה (הזמנה אמיתית) מוצקה.
- **`debug_errors=True` מתאים לבטא** (3 חברים) אבל חובה לכבות לפני קהל אמיתי (`config.py:33`).
- **טסטים** (`tests/`) מכסים resolver, engine retry-ladder, webhook-signature, memory-gating —
  אבל אין טסט end-to-end להזמנה אמיתית (כי המסלול עוד לא קיים).
