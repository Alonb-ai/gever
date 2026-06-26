# Ops — חשיפת השרת המקומי ל-WhatsApp (לא להיתקע יותר על tunnel)

## הבעיה (חזרה 4 פעמים ב-dry-runs)
ה-tunnel של **localhost.run בחינם מחליף URL כל כמה שעות** — זו התנהגות מתוכננת, לא באג
([forever-free docs](https://localhost.run/docs/forever-free/)). כל החלפה שוברת את ה-Callback
URL ב-Meta → גבר מקבל הודעות אבל לא רואה אותן → "לא עונה". וכל reconnect של ssh נותן
subdomain אקראי חדש. **אי אפשר לבדוק ככה.**

## הפתרון לפיתוח: ngrok dev domain (חינמי, קבוע)
ngrok נותן לכל חשבון **dev domain קבוע** (`xxxx.ngrok-free.dev`) ש**לא משתנה ולא פג**
כל עוד יש חשבון ([ngrok blog](https://ngrok.com/blog/free-static-domains-ngrok-users)).
מגדירים פעם אחת, מעדכנים את Meta **פעם אחת**, ונגמר הסיפור.

מגבלות החינם שמספיקות לנו בגדול: 20k בקשות/חודש, 1GB/חודש, 3 endpoints.

### Setup (פעם אחת, ~5 דק')
```bash
brew install ngrok
# נרשמים בחינם ב-https://ngrok.com → מעתיקים authtoken + ה-dev domain מה-dashboard
ngrok config add-authtoken <TOKEN>
```

### הרצה (במקום ssh ... localhost.run)
```bash
# 1. השרת (טרמינל א'):
cd ~/Desktop/GeverAI && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# 2. ה-tunnel היציב (טרמינל ב') — <DOMAIN> = ה-dev domain הקבוע מה-dashboard:
ngrok http 8000 --url https://<DOMAIN>.ngrok-free.dev
```

### Meta — פעם אחת בלבד
developers.facebook.com → WhatsApp → Configuration → Webhook:
- Callback URL: `https://<DOMAIN>.ngrok-free.dev/webhook`
- Verify token: `gever_verify_2026`
- Verify and Save · לסמן `messages`.

**ה-URL הזה קבוע — לא צריך לגעת ב-Meta שוב.** (החלפת token עדיין דורשת רק עדכון .env + restart, לא נגיעה ב-webhook.)

## הפתרון לפרודקשן: Coolify (בלי tunnel בכלל)
היעד הסופי — deploy ל-Coolify (88.198.116.222) עם URL ציבורי קבוע, בלי tunnel. דורש
שגם שם יהיו `.venv-bu` + Chrome (Linux) ל-browser-use. ראה roadmap. עד אז — ngrok לפיתוח.

## אם בכל זאת "גבר לא עונה"
ראה ה-diagnostic playbook ב-[`retro-dryrun1.md`](retro-dryrun1.md): קודם בדוק שה-Callback
URL הרשום ב-Meta חי (`curl <url>/health`), ורק אז את הטוקן.

---
**Sources:** [ngrok dev domains](https://ngrok.com/blog/free-static-domains-ngrok-users) ·
[ngrok domains docs](https://ngrok.com/docs/universal-gateway/domains) ·
[localhost.run forever-free](https://localhost.run/docs/forever-free/) ·
[localhost.run custom domains](https://localhost.run/docs/custom-domains/)
