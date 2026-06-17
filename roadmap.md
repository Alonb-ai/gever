# גבר — Roadmap & Todos

מ‑localhost היום ← הוכחת הזמנת מסעדה מדויקת. השאר מקבילי.

**מקרא:** `[x]` הושלם · `[ ]` פתוח · ⭐ המוקד היום

**שלבים:** עכשיו → היום (PoC מסעדה) → שלב 1 (תשתית שיחה) → שלב 2 (E2E) → שלב 3 (הרחבה + השקה)

---

## ✅ המוקד היום — הושג! הזמנת מסעדה מדויקת (DRY_RUN)
ה-PoC רץ מקצה לקצה: ניווט לדף הדסון לילינבלום, קריאת זמינות אמיתית, טיפול
ב"השעה המבוקשת תפוסה → הקרובה ביותר", והגעה למסך האישור עם הפרטים הנכונים.
- [x] ניווט למסעדה הנכונה (deep-link — החיפוש בדף הבית לא מנווט!)
- [x] קריאת שעות זמינות אמיתיות מהווידג'ט
- [x] טיפול בשעה לא זמינה → הקרובה ביותר (`near_time`)
- [x] מסך אישור עם פרטים נכונים ב-`DRY_RUN` — **ההוכחה** ✅
- [x] סטטוס אמיתי (🔄 → "כמעט סגור — מאשר?")
- [x] resolve שם מסעדה → Ontopo page URL (`app/automation/resolve.py`, DDG) — עובד על כל מסעדה
- [ ] "הצע שעות" כשהמבוקשת תפוסה — היום בוחר אוטומטית את הראשונה (לא תמיד הקרובה)
- [ ] הזמנה אמיתית: אישור סופי + login/טלפון (מעבר ל-DRY_RUN)

---

## זרוע 1 · 🌐 ביצוע — Browserbase + Stagehand
- [x] PoC: pipeline עובד מול Ontopo (Stagehand 3.21, Gemini driver, project id)
- [x] playbook המסעדה (`app/automation/ontopo.py`): deep-link, אימות מסעדה, זמינות, near-time, שער אישור, סטטוס אמיתי, כישלון כן
- [x] ה-PoC הגיע למסך אישור (DRY_RUN) עם פרטים נכונים
- [x] resolve שם → Ontopo page URL (`app/automation/resolve.py`, DDG + `_match_restaurant`); נבדק end-to-end (טאיזו לפי שם → מסך אישור)
- [ ] הזמנה אמיתית: אישור סופי + login/OTP/טלפון (מעבר ל-DRY_RUN)
- [ ] טיפול בשגיאות: שינוי UI / captcha / timeout
- [ ] (שלב 3) אתרים נוספים: Leaan, Eventim, 10bis

## זרוע 2 · 🧠 מוח ושיחה — Gemini + persona
- [x] `SYSTEM_PROMPT` כדמות + `character_leaks` + `gender_line`
- [x] `poc/persona_eval.py` — בדיקת אי‑סטייה (Gemini + LLM‑judge)
- [x] `poc/chat.py` — ממשק ניסוי מקומי לשיחה עם גבר
- [x] `poc/gever.py` — לולאת chat→ביצוע (חילוץ שדות + הפעלת `book_table`; first cut, הדסון)
- [ ] `understand()`: להעביר את החילוץ מ-gever.py ל-`app/llm/intent.py` כ-`Intent` מובנה
- [ ] זיהוי פעולה (restaurant/insurance/tickets) + חילוץ שדות + שאלות הבהרה
- [ ] ניהול הקשר שיחה (היסטוריה, שדות חסרים) חוצה הודעות
- [ ] להריץ `persona_eval` על כל שינוי prompt (תפיסת רגרסיות)

## זרוע 3 · 💬 ערוץ — WhatsApp (Meta Cloud API)
- [x] חיבור `webhook → pipeline → reply` (`app/main.py` + `app/pipeline.py`, מצב per-phone בזיכרון)
- [x] שליחת תשובות + סטטוס חי (`app/whatsapp/client.py`, Meta Graph API)
- [x] הזמנה ברקע (book_table איטי → לא חוסם את ה-webhook)
- [x] **לופ חי מקצה-לקצה (יוני 2026)**: App ב-Meta + מספר טסט, webhook מאומת + subscribe ל-`messages`, הודעת וואטסאפ אמיתית → גבר ענה ✅
- [ ] **System User token קבוע** במקום ה-Temporary (פג ~24ש' → גבר מפסיק לענות) — בלוקר לרציפות
- [ ] **host יציב** במקום tunnel זמני (lhr.life מתנתק → Callback URL מתיישן) — ראה זרוע 5
- [ ] אימות `X-Hub-Signature-256` לפני אמון ב-payload (כרגע אין; בסדר למספר-טסט נעול, חובה לפני קהל)
- [ ] (שלב 2) מספר עסקי אמיתי + אימות עסק ב‑Meta + פרסום ה-App
- [ ] (שלב 3) templates מאושרים להודעות מחוץ לחלון 24 ש'

## זרוע 4 · ⚙️ Backend — FastAPI + Supabase
- [x] שלד FastAPI + `/health` + webhook stub (רץ ב‑localhost)
- [ ] פרויקט Supabase + הרצת `app/db/schema.sql` (users/sessions/actions)
- [ ] `supabase_client` מחובר; CRUD בסיסי
- [ ] pipeline מלא: webhook → intent → automation → תשובה + שמירת `action`
- [ ] (שלב 2) פרופיל מוצפן (Fernet, `ENCRYPTION_KEY`)

## זרוע 5 · ☁️ תשתית — Docker / Coolify
- [x] `Dockerfile` + `.dockerignore`; `pyproject` בר‑התקנה
- [x] (עכשיו) הרצה מקומית ב‑localhost (venv + uvicorn) + tunnel זמני (lhr.life) — הספיק ללופ הראשון
- [ ] **⭐ הצעד הבא לרציפות** — deploy ל‑Coolify: app חדש מה‑repo (בונה את ה-`Dockerfile`, uvicorn:8000), env ב‑UI (תוכן `.env`), subdomain + SSL (Traefik). ואז Callback URL ב-Meta = הסאב-דומיין הקבוע במקום ה-tunnel
- [ ] אי‑התנגשות עם n8n/Coolify (80/443/5678/8000 תפוסים → דרך Coolify בלבד, לא docker run -p)

## זרוע 6 · 💳 תשלום — Lemon Squeezy
- [ ] חשבון + store; מוצרי מנוי (trial / basic ₪29 / pro ₪79)
- [ ] checkout מתארח (Merchant of Record — לא נוגעים בכרטיסים)
- [ ] webhook של Lemon Squeezy → עדכון `plan` ב‑`users`
- [ ] אכיפת מכסות לפי plan (5 / 30 / ללא הגבלה)

## זרוע 7 · 📣 שיווק — GTM (פירוט: docs/MARKETING.md)
- [ ] לוגו + מותג (וייב ישראלי/סחבקי)
- [ ] דף נחיתה: וייטליסט + click‑to‑WhatsApp (Next.js/Vercel)
- [ ] סרטון דמו ב‑Remotion (9:16)
- [ ] Instagram + Twitter/X (אורגני + Meta Ads ממומן)
- [ ] הפצה IRL (בטא חברים) + referral + analytics
