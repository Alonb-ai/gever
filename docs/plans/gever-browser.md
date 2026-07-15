# דפדפן גבר — עטיפת Live View בקיר-כרטיס (2026-07-15)

> הבעיה (נבדק חי בוואטסאפ, מובייל): לינק ה-Live View של Browserbase (1) חושף
> `browserbase.com` — מסגיר אוטומציה, חוק ברזל של הדמות; (2) **הקלדה במובייל לא
> עובדת** — טאפ על שדה בלייב-ויו לא פותח מקלדת (screencast, אין input אמיתי).
> הפתרון: עמוד בדומיין שלנו שעוטף את הסשן, עם ערוץ הקלדה משלנו.
> **שלב א' (לינק ממותג + עטיפה) ממומש בקוד — ראה "מה ממומש" למטה.**

---

## ממצאי המחקר (docs.browserbase.com + PoC חי, 2026-07-15)

### 1. אנטומיית ה-endpoints

`GET /v1/sessions/{id}/debug` מחזיר ארבעה שדות:

| שדה | צורה | הערות |
|---|---|---|
| `debuggerFullscreenUrl` | `https://www.browserbase.com/devtools-fullscreen/inspector.html?wss=connect.browserbase.com/debug/{sessionId}/devtools/page/{pageId}?debug=true` | מה שאנחנו שולחים היום |
| `debuggerUrl` | כנ"ל עם מסגרת דפדפן מדומה | לא רלוונטי לנו |
| `wsUrl` | `wss://connect.browserbase.com/debug/{sessionId}/devtools/browser/{uuid}` | **CDP ברמת browser, בלי API key!** |
| `pages[]` | `{id, url, title, faviconUrl, debuggerUrl, debuggerFullscreenUrl}` פר-טאב | לריבוי טאבים |

תובנת מפתח: **ה-secret היחיד בערוץ ה-debug הוא ה-session id** (UUID). אין token
חתום ואין header — מי שמחזיק את ה-URL יכול גם לצפות וגם לשלוט. לעומת זאת
`connectUrl` (של הסשן עצמו) נושא `signingKey` — סוד צד-שרת, לעולם לא ללקוח.

### 2. iframe — נתמך רשמית ואומת חי

- התיעוד נותן snippet רשמי: `sandbox="allow-same-origin allow-scripts"` +
  `allow="clipboard-read; clipboard-write"`; מצב read-only = `pointer-events:none`.
- אומת ב-PoC: עמוד ה-live view חוזר **בלי `X-Frame-Options` ובלי CSP
  `frame-ancestors`** → embeddable מכל דומיין.
- `&navbar=false` מוריד את הסרגל העליון (עוד עקבה של browserbase).
- אירוע סיום: `postMessage` עם `"browserbase-disconnected"` כשהסשן נסגר.

### 3. מקלדת מובייל — אין פתרון רשמי; יש פתרון client-direct שהוכח

- התיעוד מפורש: *"mobile keyboards aren't officially supported"*. ההמלצה שלהם:
  מקלדת וירטואלית משלנו (למשל react-simple-keyboard) שמעבירה key events —
  אצלם דרך השרת אל Playwright (`page.keyboard.press()`), **שאצלנו אסור (PCI)**.
- הנתיב שלנו: **CDP ישירות מהדפדפן של הלקוח אל Browserbase** — בלי לעבור בשרת.

### 4. מה ה-PoC הוכיח בפועל (סשנים אמיתיים, שוחררו בסוף)

1. **חיבור CDP שני במקביל ל-agent**: בזמן שחיבור "agent" פתוח על `connectUrl`,
   חיבור שני על `wsUrl` (בלי שום header) וחיבור שלישי page-scoped (ה-`wss=`
   מתוך `debuggerFullscreenUrl`) התחברו ועבדו — במקביל.
2. **הזרקת טקסט**: `Input.insertText` + `Input.dispatchKeyEvent` מהחיבורים
   הטוקן-פחות נחתו בשדה הממוקד: הערך `'4242 4242 4242 4242 12/29 CVV333'`
   נקרא בחזרה דרך חיבור ה-agent.
3. **מדפדפן אמיתי**: עמוד עטיפה מקומי (iframe live view + `<input>` שלנו +
   `WebSocket` מ-JS) — ה-WS התחבר **עם Origin header של דפדפן** (לא נדחה),
   והקלדה בשדה שלנו נחתה בשדה של הסשן המרוחק (`' 999X'` נוסף לערך).
4. עמוד ה-live view נטען ב-iframe ומציג את הסשן.

מה שנשאר לא-מוכח (דורש מכשיר אמיתי — אלון): פתיחת מקלדת iOS/Android על
ה-input *שלנו* (input רגיל בעמוד שלנו — צפוי לעבוד, זו כל הפואנטה), וטאפ על
שדה בלייב-ויו כדי להעביר פוקוס בסשן (קליק עכבר עובד; טאפ אמור להיתרגם לקליק).

---

## העיצוב — שלוש שכבות

### שלב א' — לינק ממותג + עמוד עטיפה ✅ ממומש (לבטא)

- `app/live_link.py`: `wrap(live_url)` ← token אקראי (`secrets.token_urlsafe(6)`,
  48 ביט) במפה in-memory עם TTL של 1800s (מיושר לתקרת סשן BB). in-memory
  בכוונה: restart מריץ `sweep_orphan_sessions` שמשחרר את כל הסשנים — token
  שנשמר היה מצביע על סשן מת ממילא, אז אין מה להתמיד ב-prefs.
- `GET /b/{token}` ב-`app/main.py`: מגיש עמוד עטיפה RTL ממותג עם ה-live view
  ב-iframe (`&navbar=false`), ומאזין ל-"browserbase-disconnected". token מת/פג
  → 404 ידידותי ("תכתוב לגבר בוואטסאפ").
- **עיצוב = דף הנחיתה, לא המצאה**: העמוד משתמש בדיוק בפלטה ובפונטים של
  `web/index.html` (רקע `#16140f`, משטח `#211e17`, טקסט `#F3ECDD`, משני
  `#c4bcad`, accent `#FF6B35`, פוקוס `#54c9c9`; IBM Plex Sans Hebrew + Alef,
  לוגו "גבר" עם נקודה כתומה). מקור האמת לטוקנים:
  `docs/marketing/design-tokens.md` (בחילוץ) — כל שינוי עתידי בעמוד יונק משם.
- pipeline: שני אתרי קיר-הכרטיס (`run_booking`, `run_commit`) עוטפים את
  `live_view_url(...)` ב-`live_link.wrap(...)` — ההודעה בוואטסאפ נושאת
  `https://geverai.duckdns.org/b/xxxxxxxx` בלבד.
- מה זה פותר: חשיפת browserbase (הדמות), ודסקטופ עובד מלא (הקלדה בתוך
  ה-iframe עובדת בדסקטופ). מה זה לא פותר: מקלדת מובייל.

### שלב ב' — הקלדה במובייל: שדה שלנו + CDP client→BB (הצעד הבא, לבטא אם א' לא מספיק)

הצנרת הוכחה ב-PoC; נשאר UI + בדיקת מכשיר אמיתי.

- השרת שולף את `debuggerFullscreenUrl`, גוזר ממנו את פרמטר ה-`wss=`
  (page-scoped CDP), ומטמיע את שניהם **בתוך ה-HTML** של `/b/{token}`
  (לא ב-query string — לא שמים סודות ב-URL).
- העמוד: iframe הלייב-ויו למעלה, ולמטה שורת `<input>` אמיתית שלנו ("הקלד כאן —
  נכנס ישר לשדה שבמסך"). input אמיתי בדף שלנו ⇒ טאפ פותח מקלדת native.
  העיצוב ממשיך לינוק מ-`docs/marketing/design-tokens.md` (אותו design system
  של דף הנחיתה) — לא ממציאים פלטה.
- JS בעמוד: `new WebSocket("wss://connect.browserbase.com/debug/{sid}/devtools/page/{pid}?debug=true")`,
  ועל כל שינוי בשדה — diff פשוט: תווים שנוספו → `Input.insertText`; מחיקה →
  `Input.dispatchKeyEvent(Backspace)`; Enter → dispatchKeyEvent(Enter).
- הפוקוס בסשן: הלקוח מטאפ על השדה הרצוי בלייב-ויו (טאפ = קליק = פוקוס מרוחק),
  ואז מקליד בשורה שלנו. אפשר גם כפתור "שדה הבא" ששולח Tab.
- **PCI**: ספרות הכרטיס זורמות דפדפן-הלקוח → connect.browserbase.com → אתר
  היעד. השרת שלנו מטפל רק ב-URL — אף פעם לא בהקלדות. אסור להוסיף שום ממסר
  מקשים צד-שרת (זה בדיוק מה שהתיעוד של BB מציע — ואצלנו זה פסול).
- רמת ביטחון: **גבוהה (~85%)**. הצנרת כולה הוכחה מדפדפן אמיתי; הנעלמים:
  התנהגות iOS Safari (wss מ-https — תקין תקנית), ותרגום טאפ→פוקוס בלייב-ויו
  במובייל. שניהם נבדקים בחמש דקות עם מכשיר של אלון על ה-PoC הקיים.

### שלב ג' — ליטושים (אחרי הבטא, לפי כאב אמיתי)

- כפתור "סיימתי ✅" שמדווח לשרת שלנו → גבר מאמת בסשן שההזמנה נסגרה (קורא את
  המסך דרך חיבור ה-agent) ושולח אישור בוואטסאפ + משחרר את הסשן.
- viewport מובייל (Emulation.setDeviceMetricsOverride דרך חיבור ה-agent) כדי
  שהאתר יוצג צר וקריא בטלפון — רק אם הקריאות בפועל גרועה.
- מקלדת מספרים (`inputmode="numeric"`) לשדות כרטיס, וכפתורי Tab/Enter.
- קשירת token ללקוח (טלפון) + one-time-use — כשיש יותר ממשתמשי-בטא-מהימנים.

---

## Sequence מדויק (שלב א'+ב')

```
1. browser-use agent פוגע בקיר-כרטיס  →  bu_runner מדווח card_required
2. book_table_bu משאיר את הסשן חי (keepAlive, קיים)  →  session_id ב-details
3. pipeline: live_view_url(session_id)  →  GET /sessions/{id}/debug
4. live_link.wrap(url)  →  token אקראי ב-_links (TTL 30 דק')
5. WhatsApp: "נשאר רק להשלים את הפרטים כאן: https://geverai.duckdns.org/b/abc123"
6. הלקוח פותח  →  GET /b/abc123  →  עמוד עטיפה (iframe live view, navbar=false)
   [שלב ב': העמוד כולל גם את ה-wss ה-page-scoped, מוטמע ב-HTML]
7. [שלב ב'] JS בעמוד פותח WebSocket ישירות ל-connect.browserbase.com (בלי השרת שלנו)
8. הלקוח מטאפ על שדה בלייב-ויו (פוקוס מרוחק), מקליד בשורה שלנו
   →  Input.insertText מהדפדפן שלו ישר ל-BB  →  התווים נחתים בשדה באתר
9. הלקוח מסיים ולוחץ על כפתור האישור של האתר בתוך הלייב-ויו
10. "browserbase-disconnected" / חזרה לוואטסאפ  →  ההמשך הקיים (confirm flow);
    הסשן משוחרר ב-flow הקיים או בתקרת ה-1800s
```

---

## סיכוני אבטחה והטיפול בהם

| סיכון | ניתוח | טיפול |
|---|---|---|
| ניחוש token | 48 ביט, TTL 30 דק' — ‎2^48‎ ניסיונות בחלון קצר, לא ריאלי | מספיק לבטא; rate-limit על `/b/` אם יהיה קהל |
| דליפת ה-URL הגולמי | ה-capability האמיתי הוא ה-session UUID — מי שמחזיק אותו שולט בסשן בלי API key | ה-URL הגולמי לא נשלח יותר לאף אחד; נשאר רק בזיכרון השרת. שחרור סשן מהיר בסוף flow (קיים) מקצר את חלון החיים |
| token של לקוח אחר | אין enumeration; token נשלח רק ל-thread של בעל ההזמנה | לבטא: החזקת הלינק = הרשאה (בדיוק המודל של BB עצמם). אחרי הבטא: קשירה לטלפון |
| PCI | ספרות עוברות רק דפדפן-לקוח→BB→אתר | אסור להוסיף ממסר צד-שרת. `connectUrl` (signingKey) לעולם לא יוצא מהשרת |
| XSS/הזרקה בעמוד | ה-live URL מגיע רק מ-API של BB; ה-token הוא מפתח מילון | תבנית סטטית, בלי echo של קלט משתמש |
| סשן חי אחרי סיום | לקוח שלא סוגר → הסשן מחויב עד timeout | קיים: תקרת 1800s + sweep בעליית שרת + שחרור ב-flow |

---

## מה ממומש (שלב א', בקוד, בלי commit)

- `app/live_link.py` — `wrap` / `resolve` / `page_for` + תבניות העמוד (עטיפה + 404).
- `app/config.py` — `public_base_url` (ברירת מחדל: הפרוד); `.env.example` עודכן.
- `app/main.py` — `GET /b/{token}`.
- `app/pipeline.py` — שני אתרי קיר-הכרטיס עוטפים ב-`live_link.wrap`.
- טסטים: `tests/test_live_link.py` (wrap/resolve/תוקף/route/404) + עדכון
  `tests/test_liveview.py` (ההודעה נושאת לינק ממותג, לא bb).
- שער איכות: ruff ✓, ‎148 passed‎ ✓.

**מה נשאר לפני שליחה ללקוח אמיתי:** בדיקת מובייל של אלון על שלב א' (העטיפה),
ואם מקלדת עדיין חסומה — שלב ב' לפי המתווה למעלה (הצנרת כבר מוכחת).
