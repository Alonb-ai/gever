# בחינה מעמיקה — 3 הורטיקלים החדשים + זירוז מטא (23.7.2026)

> תוצר של 4 סוכני מחקר (קוד + web מאומת). עונה לשאלה: "ישים באמת ברמה גבוהה, או חצי-חצי?"
> משלים את המטריצה ב-`handover-2026-07-23.md` §4 — לא מחליף אותה.

## TL;DR — פסיקה פר-ורטיקל

| ורטיקל | פסיקה | התנאי |
|---|---|---|
| **ביטול מנויים** | ✅ גבוה — אבל **היברידי**, לא דפדפן-טהור | דפדפן ל-partner+cellcom, **נתיב-מייל** לכל השאר (החוק מחייב את הספק) |
| **ערר חניה** | ✅ גבוה, לא חצי-חצי | ת"א מוכן; סבב-כוונון אחד ל-‏cityforms‏ פותח חיפה+ראשל"צ + עשרות ערים |
| **‏voice‏** | חצוי: voice-notes ✅ כמעט קיים · שיחות-טלפון ⚠️ לא נבדק | לולאת voice-notes = 1-2 ימים; טלפון מחכה ל-PoC + תמחור ‏pay-per-task‏ |

---

## 1. ביטול מנויים — היברידי דפדפן+מייל

**הממצא המשפטי שמשנה הכל:** סעיף 14ט לחוק הגנת הצרכן מחייב כל עוסק לקבל הודעת ביטול
**בדוא"ל** (וגם בע"פ/דואר/אינטרנט + "קישור ייעודי לביטול" בולט); בעסקה מתמשכת הביטול נכנס
לתוקף **תוך 3 ימי עסקים** ממסירת ההודעה (ס' 13ד(ג)) — בלי תלות בטופס באתר.
מקורות: [נוסח החוק](https://he.wikisource.org/wiki/חוק_הגנת_הצרכן) · [כל-זכות — ביטול עסקה מתמשכת](https://www.kolzchut.org.il/he/ביטול_עסקה_מתמשכת) · [נבו](https://www.nevo.co.il/law_html/law00/70305.htm).
**תקדים עסקי חי:** "נתק אותי" שולח הודעות ניתוק במייל/פקס בשם לקוחות מ-2011 ([natekoti.co.il](https://natekoti.co.il/), [TheMarker](https://www.themarker.com/technation/2011-11-11/ty-article/0000017f-e2f0-d75c-a7ff-fefdf9960000)).

- נתיב-המייל מכסה **7/7 ספקים כולל החסומים** (hot/yes/holmesplace/bezeqint/space); דטרמיניסטי, אפס דפדפן, אפס עלות-לריצה, חותמת-זמן ראייתית.
- HOT: דף "סיום התקשרות" רשמי קיים ([hot.net.il](https://www.hot.net.il/media/HOTnet/HOT_disconnect2023/index.htm)) — זה ה-URL שקיבל 404 בדפדפן/200 ב-curl → מאשר חסימת bot/IP, לא דף מת. yes: כתובות ביטול מפורסמות (לאמת לפני שימוש).
- **פערים בענף `feature/cancel-subscriptions`:** (א) אין חיווט intent/pipeline — אין `task_type="cancel"` בכלל, לקוח לא יכול לבקש ביטול; זה החלק הגדול (בהיקף של הביטוח). (ב) לגבר **אין שליחת מייל** — ה-"email מהיר" הוא הקלדה בטופס, לא ‏SMTP‏. תשתית מייל (ספק טרנזקציוני + ‏SPF/DKIM‏ + תבנית עם שם+ת"ז+שורת-שליחוּת + ‏Reply-To‏ ללקוח) ≈ 1-2 ימים. (ג) אף ריצת commit חיה. הקוד הקיים איכותי, 605 טסטים ירוקים.
- **‏Browserbase Scale‏ — לא עכשיו:** ‏Advanced Stealth‏ רק בתוכנית ‏Scale‏ (מכירה ארגונית, מעל $99 ([pricing](https://www.browserbase.com/pricing))). ניסוי זול שלא נוסה: `proxies: true` כלול כבר ב-$20 — probe אחד לפני כל מסקנה. גם אם יעבוד — מרוץ חימוש; המייל עוקף.
- **החלטה #1 מה-handover:** ההמלצה = (א)+(ב). לא (ג) עכשיו, לא (ד) — דפדפן-בלבד נשאר 2/7; היברידי = 7/7 עם התחייבות חוקית.

## 2. ערר חניה — כוונון אחד פותח הרבה ערים

**התגלית:** חיפה (`por124`) וראשל"צ (`por140`) על **אותה פלטפורמה** — `cityforms.co.il`
(‏eForms‏ בסגנון ‏AgilePoint‏, JS-כבד צד-לקוח) של "אוטומציה החדשה"/‏ONE City‏, שמשרתת ~60%
מהרשויות ([ויקיפדיה](https://he.wikipedia.org/wiki/אוטומציה_החדשה), [ONE City](https://www.pc.co.il/news/372039/)). נמצאו סאבדומיינים חיים נוספים: נתניה (`por148`), כרמיאל (`por193`), בני-ברק.
**כוונון אחד → שתי ערים מיד + כל עיר נוספת = שורת dict.**

- **"5 consecutive failures" = כשל קליקים בטופס מרונדר, לא חסימה.** זה `max_failures` הדיפולטי של browser-use. **התקדים נפתר אצלנו:** מפת מושבים הוט-סינמה → בלוק hint פר-פלטפורמה (`bu_runner.py:250-258` ב-main, מתכון ‏evaluate‏ שנמדד חי). אותו סדר-גודל: יום-יומיים.
- **ירושלים:** מערכת עצמאית מאחורי ‏Akamai‏ — לדחות לסוף; אם WAF חוסם → גניזת העיר, לא הורטיקל.
- **ביקוש (מאומת):** ת"א ~762K דוחות/שנה, ~105K בקשות ביטול, **~40% מתקבלות** ([ynet](https://www.ynet.co.il/economy/article/s1tn6i11wa), [חופש המידע](https://www.meida.org.il/15936)); ירושלים 100K+ עררים/שנה, 30-40% קבלה ([N12](https://www.mako.co.il/news-israel/2022_q4/Article-bc2d9d9855d2481026.htm)). מתחרים (‏Road Protect‏, ‏FineFix‏) רק מכינים מסמך — גבר מגיש בפועל = בידול. הסתייגות: ורטיקל ‏wow‏/רכישה, לא ‏retention‏.
- **סדר מומלץ:** (1) ת"א — ריצת commit חיה ולשחרר. (2) סבב כוונון ‏cityforms‏ — קודם ריצה סדרתית נקייה (concurrency 1! חלק מהכשלים אולי רעש-פרוקסי) + ניתוח יומן + hint. (3) ירושלים בסוף.
- **החלטה #2 מה-handover:** להשקיע — התשואה-לכוונון גבוהה בזכות הפלטפורמה המשותפת.

## 3. voice — שני ורטיקלים שונים

**(א) לולאת voice-notes ב-WhatsApp — כמעט קיימת.** קלט קולי + תמלול ‏Gemini‏ **כבר בפרוד**
(`app/main.py:177`, `app/pipeline.py` `handle_voice`, `app/llm/transcribe.py`; `upload_media`
כבר קיים ב-`app/whatsapp/client.py`). הפער לסגירה: ‏TTS‏ (קוד ב-PoC) → ‏ffmpeg‏ ל-ogg/opus →
`send_audio` (~15 שורות, `"voice": true`, עד 512KB לכפתור-נגינה ([Meta docs](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/audio-messages))). **הערכה: 1-2 ימים.**
עלות סיבוב קולי ~₪0.05-0.18 (‏TTS Eleven v3‏ ~$0.10/1K תווים ([pricing](https://elevenlabs.io/pricing/api))) — פי 2-4 מטקסט, לא שובר ₪15/חודש. זה ה-quick win.

**(ב) שיחות טלפון לנציג (מה שהענף מתכנן) — לא עדיין.** תכנון+משפטי ברמה גבוהה
(`voice-architecture.md`, `voice-research.md`), אבל ה-PoC לא הורץ (מחכה לחשבון ‏ElevenLabs‏ של
אלון — free tier מספיק). עלות שיחה ₪3-12 (~$0.15-0.17/דקה כולל ‏Twilio‏ לנייד ישראלי
([תעריפים](https://www.twilio.com/en-us/voice/pricing/il))) → חייב ‏pay-per-task‏ ₪20-30.
סיכונים פתוחים: ‏latency‏ בעברית, טבעיות ‏v3‏ ב-streaming, ו**האם נציג ישראלי משתף פעולה עם בוט
מזוהה** — רק פיילוט יגלה. עברית = ‏Eleven v3‏ בלבד → תלות בספק יחיד בלי fallback.

## 4. זירוז אישור מספר במטא (נספח)

הוספת ‏payment method‏ לא מגישה כלום לאישור. אחרי שבוע, לבדוק לפי הסדר:
1. ‏Security Center‏ → אם ‏business verification‏ בסטטוס ‏Not started‏ — צריך ללחוץ ‏Start Verification‏ ידנית ([respond.io](https://respond.io/help/whatsapp/meta-business-verification)).
2. סטטוס המספר ב-API: `GET /{phone-number-id}?fields=status,name_status,code_verification_status`. אם ‏Pending‏ → להריץ `POST /register` עם ‏PIN‏ — הפתרון שסגר תקיעות של חודשים ([Meta community](https://developers.facebook.com/community/threads/1443903850043544/)).
3. ‏Display name‏ שנדחה בשקט / מספר שעדיין רשום ב-WhatsApp רגיל (למחוק את החשבון באפליקציה).
4. תמיכה: ‏developers.facebook.com/support‏ — מענה מוצהר תוך 24 שעות בימי עסקים.

**רלוונטי לבטא:** מאז 2024 לא חייבים ‏business verification‏ מלא כדי לשלוח — מספר ‏CONNECTED‏ + שם מאושר מספיקים, עד ~250 שיחות יזומות/יום (נכנסות לא נספרות) ([360dialog](https://docs.360dialog.com/docs/resources/meta-business-verification), [whatsera](https://whatsera.com/blog/whatsapp-api-without-facebook-business-verification-the-new-process/)) — כלומר הבטא לא תלויה ברישום עוסק.

---

## השלכות על ההחלטות הפתוחות (handover §6)

1. **ביטול:** (א)+(ב) — היברידי. תלות חדשה: תשתית מייל (1-2 ימים) + חיווט pipeline.
2. **חניה:** להשקיע — ת"א עכשיו, ‏cityforms‏ סבב אחד, ירושלים בסוף.
3. **משפטי (תיקון עובדתי):** privacy+consent **כבר קיימים** על `feature/legal-tos` (77d28b3); חסר רק lawyer-review-checklist.
4. **voice:** לפצל את ההחלטה — voice-notes עכשיו (זול), טלפון אחרי PoC.
