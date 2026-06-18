# מחקר ל-גבר: סינתזה ומפת דרכים

> מסמך עבודה פנימי. שלושה מקורות מחקר: (א) ניתוח Botivation כמתחרה/השראה, (ב) אמינות אוטומציית דפדפן עם Stagehand/Browserbase ממופה לבאגים שלנו, (ג) מה דרוש כדי שצ'אטבוט AI יהיה מוצר שמשלמים עליו ושמחזיק לקוחות. מקורות מלאים בסוף.

---

## 1. סיכום מנהלים

גבר הוא עוזר וואטסאפ שמבצע משימות אמיתיות במקום המשתמש (מתקשר, מזמין, ממלא טפסים). שלוש מסקנות שמכתיבות את העבודה הקרובה:

1. **הבידול שלנו הוא ביצוע, לא נדנוד.** Botivation מוכרים *אכיפה רגשית* ("הבוט שלא יורד לכם מהוריד") אבל בסוף המשתמש מבצע בעצמו. גבר עושה את העבודה. זה היתרון התחרותי המרכזי וחייב להיות הכותרת בכל מקום — אבל הוא גם מקור הסיכון: אם נראים כמו "עוד נודניק" בלי תוצאות אמיתיות, נאבד אמון. כל החלטה מוצרית צריכה לחזק את ההוכחה ש"הוא באמת סגר".

2. **האמינות הטכנית היא הסיכון מספר אחת.** הבאגים שלנו (בחירת תאריך שלא נתפסת, אישור על תאריך שגוי) הם "כשלים שקטים" קלאסיים של Stagehand: `act()` מחזיר `success:true` בלי שהפעולה באמת השפיעה על המצב. הפתרון ידוע ומתועד — אטומיות + observe-before-act + extract לאימות אחרי כל צעד קריטי, ולעולם לא ללחוץ "אישור" בלי gate שמשווה את מה שבמסך למה שביקשנו. זה P0.

3. **המלכודת היא שימור, לא רכישה.** אפליקציות AI ממירות ל-trial וגובות תשלום ראשון בקלות, אבל churn מהיר ב-30% (שימור שנתי 21% מול 31% לאפליקציות לא-AI). שני המגנים החזקים: (א) הרגל יומיומי — שגבר ייכנס לשגרה בשבוע הראשון לפני ה"novelty cliff"; (ב) זיכרון מתמשך בין שיחות שמייצר switching cost.

החיבור בין השלושה: הקול והבידול של Botivation מביאים אנשים פנימה; אמינות הביצוע + הרגל + זיכרון משאירים אותם, וזה מה שמצדיק תשלום.

---

## 2. Botivation — מה לאמץ ל-גבר

Botivation הוא בוט וואטסאפ ישראלי נגד דחיינות (צוות של 2 מתל אביב), freemium ב-14.99 ש"ח/חודש, עם traction אמיתי (מאות נרשמים מפוסט לינקדאין, סיקור mako + ערוץ 13). מה שעובד אצלם ורלוונטי לנו:

### 2.1 הקול בכל פיקסל (אימוץ ישיר, זול, השפעה גבוהה)
אצל Botivation אין אף מחרוזת ניטרלית. ה-FAQ נקרא "שאלות ותירוצים", תיבת המשוב "פינת התלונות והפרגונים", שגיאת מייל אומרת "שגיאה קטנה והמייל הולך לפח", כפתור ה-decline הוא "לא תודה, אני אמשיך לדחות משימות ואחכה בתור". הקול עקבי 100% מה-hero ועד הודעות השגיאה.
- **ל-גבר:** הגדר *פרסונה אחת חדה* (גברי, ענייני, "בן אדם שסוגר") וכתוב בה את כל האתר והבוט — hero, כפתורים, אישורים, שגיאות, מיילים. זו ההצלחה הכי גדולה שלהם וההכי זולה להעתקה.

### 2.2 Hero סביב תירוץ שהמשתמש מזהה את עצמו בו
Botivation פותחים ב"נמאס לך לחרטט ש..." עם רוטציית תירוצים ("מחר אני יושב ללמוד / נכנס לכושר / קם בזמן") — לא סביב פיצ'רים.
- **ל-גבר:** פתח ב-pain מוכר עם רוטציה של דברים שגבר ישראלי דוחה ("תזמין שרברב / תחדש דרכון / תחזור לחבר"), לא ב"עוזר AI חכם לוואטסאפ".

### 2.3 מיקום נגד הקטגוריה, לא בתוכה
הם אמרו במפורש "לא עוד שעון מעורר".
- **ל-גבר:** "לא עוד צ'אטבוט / לא עוד ChatGPT בוואטסאפ — אלא מישהו ש*באמת סוגר* את המשימה במקומך." הדגש שהוא מבצע פעולות אמיתיות. זה היתרון של גבר על Botivation, שרק *מנדנד* שתבצע בעצמך. הפוך את ההבדל הזה לכותרת.

### 2.4 Social proof שהוא גם הפצה — "קיר הדחיינים"
מנגנון מקורי: feed ציבורי ואנונימי שמשתמשים מעלים אליו צילומי מסך של שיחות עם הבוט (עם כלי טשטוש מובנה), עם reactions ושיתוף. זה UGC שמייצר proof + הומור + הפצה אורגנית בו-זמנית, במקום testimonials.
- **ל-גבר:** "מה גבר סגר השבוע" — גלריה אנונימית של משימות שנסגרו (צילומי מסך מטושטשים) עם כפתור שיתוף מובנה. חזק במיוחד אצלנו כי טענת הערך היא ביצוע אמיתי — זו הוכחה ש"הוא באמת מבצע".

### 2.5 פרסונה שהמשתמש בוחר
4 פרסונות אצלם (הסמל הקשוח, המעודדת, הפולניה, הסטלן); ~50% בוחרים בסמל הקשוח. אנשים מתחברים לאופי, לא ל-tool.
- **ל-גבר:** בחירת סגנון תקשורת ("ישיר וקצר" / "חבר'ה" / "אסיסטנט מנומס"). מגדיל engagement, נותן הרגשת בקרה, זול ליישום (system prompt).

### 2.6 Freemium עם hook פסיכולוגי ותמחור שקוף
חינם מוגבל (5 ימים/חודש) ואז "מקפיא" אותך, עם הסבר כן *למה* לשלם ("השרתים שלנו לא רצים על כפיים... ברגע שמשלמים, מחויבים"), מחיר נמוך + "נעילת מחיר לשנה". סליקה ב-Lemon Squeezy.
- **ל-גבר:** trial מוגבל (X משימות שנסגרו), הסבר תמחור בקול המותג, anchor של "נעילת מחיר מוקדם".

### 2.7 ויראליות בתוך המוצר
feature "הסגרת חברים" — לשלוח את הבוט על חבר ("הלינק הועתק. עכשיו אפשר להסגיר חברים"). referral מובנה בזרימה, לא רק באנר.
- **ל-גבר:** "תעביר משימה לחבר" / "תזמין חבר לראות מה גבר סגר לי".

### 2.8 Go-to-market של launch מוקדם
waitlist + PR + לינקדאין, בלי קמפיין ממומן כבד. הזווית שעבדה: "ישראלים בנו בוט עצבני".
- **ל-גבר:** זווית סיפורית "עוזר וואטסאפ ישראלי שבאמת סוגר משימות", פנייה ל-Nexter/mako, פודקאסטים (startupforstartup), לינקדאין.

---

## 3. Browserbase / Stagehand — דרך לאמינות, ממופה לבאגים שלנו

הבאגים שלנו: **בחירת תאריך שלא נתפסת** ו**אישור על תאריך שגוי**. אלה לא מקרים אקראיים — אלה דפוס מתועד.

### 3.1 שורש הבעיה: כשל שקט
- Stagehand מדווח ~89% הצלחה במשימות נפוצות אבל רק ~75% במשימות חדשות/מורכבות. בזרימה ארוכה (תאריך → שעה → אישור) ההסתברות המצטברת לכשל גבוהה — חייבים אימות פר-צעד.
- `act()` יכול להחזיר `success:true` בלי שהפעולה באמת השפיעה על המצב. **Issue #693** מתעד ש-act/extract לא נכשלים גם כשהאלמנט מחוץ ל-viewport (צריך גלילה) — Stagehand פועל על אלמנט לא-נראה ומחזיר הצלחה. זה בדיוק "בחירת תאריך שלא נתפסת".
- `act()` על XPath יכול להחזיר 2 selectors שרק אחד מהם באמת לוחץ (**#1434**); act() על ObserveResult לא תמיד משכפל את page.click — לפעמים הקליק לא קורה למרות success (**#795**).
- **אין אימות מובנה אחרי פעולה.** Stagehand לא מוודא אוטומטית שהפעולה הצליחה מעבר להחזרת ActResult. האחריות עלינו.

### 3.2 הדפוסים לתיקון (ממופים לבאג)

| באג שלנו | סיבה | תיקון |
|---|---|---|
| בחירת תאריך שלא נתפסת | אלמנט מחוץ ל-viewport / 2 selectors / קליק שלא קורה | scroll-into-view לפני, observe→act, extract אחרי שמאמת שהתאריך נבחר |
| אישור על תאריך שגוי | אישור בלי לבדוק שהמצב תואם | **gate אימות לפני אישור**: extract של `{selectedDate, selectedTime}` מהדף, אסרציה מול הצפוי, ורק אז ללחוץ אישור |
| כשלים מצטברים בזרימה | פעולה רב-שלבית ב-act() אחד | פירוק לפעולות אטומיות עם אימות בין כל אחת |

### 3.3 העקרונות
- **Observe-before-act:** `observe()` מחזיר descriptor (selector, method, args) שאפשר לבדוק/ללוגג, ואז להעביר ישירות ל-`act()` בלי קריאת LLM נוספת. מונע "זחילת DOM" בין תכנון לביצוע, מוריד עלות+latency, ופותר את בעיית 2-ה-XPaths.
- **אטומיות = חוק ברזל:** כל act() = פעולה בודדת ספציפית ("Click the date 15"), לא "בחר תאריך ואשר". תיאור לפי פונקציה/טקסט ("the Sign In button"), לא לפי מראה ("the blue button").
- **extract לאימות אחרי כל צעד קריטי:** לקרוא בחזרה את הערך מה-UI (לא מהקלט שלנו) עם Zod schema, ולהשוות לצפוי. אם לא תואם — לזרוק שגיאה / לנסות שוב, לעולם לא להתקדם. זה הופך כשל שקט לכשל קולני.
- **Retries + timeout פר-צעד:** בקשות LLM שעושות timeout מנוסות פעמיים כברירת מחדל (`max_retries` ניתן לכוונון). זה מטפל בכשלי-רשת/LLM, *לא* בכשל לוגי של בחירה שגויה — את זה תופס ה-extract.
- **Self-healing (v3):** caching של selectors + נפילה לסוכן מלא כש-selector נשבר. עוזר להתאושש משינוי DOM, *לא* תחליף לאימות.

### 3.4 מצב agent, עלות, סשנים
- **DOM mode** (כל LLM, variables/streaming/structured output, מהיר וזול) עדיף ל-CUA/vision למסכי הזמנה עם DOM זמין. round-trip של screenshots דרך מודל מולטימודלי מוסיף 1-3 שניות לכל צעד. שמור vision/hybrid רק למסכים שבאמת לא נגישים דרך DOM.
- **maxSteps** ברירת מחדל 20 — הגדר נמוך (8-12) לזרימת הזמנה ידועה כדי לחסום לולאות יקרות. agent רק כ-fallback לזרימה קריטית.
- **captcha:** Browserbase פותר אוטומטית (reCAPTCHA v2 ~92%, hCaptcha ~88%, Turnstile ~95%), עד 30 שניות. תמחר את ה-30 שניות ב-timeouts, אל תניח כשל.
- **סשנים ארוכים (10+ דק') מתנתקים** ("WebSocket is not open" / "Target closed"): `keepAlive:true` + reconnect ל-CDP עם exponential backoff. התאם אזור Browserbase לאזור הפרוקסי; אינטרוול רוטציית פרוקסי ארוך ממשך המשימה.
- **observability:** שמור session replay של Browserbase + trace לכל פעולה (instruction, observed selector, ActResult, extract-אחרי). דגום שבועית את 10 הכשלים הגרועים — כך תופסים דפוסי כשל שקט מצטברים.
- **אבטחה:** העבר נתונים רגישים (פרטי משתמש/תשלום) דרך `variables`, לא בתוך הפרומפט, כדי שלא ידלפו ללוגים.

---

## 4. צ'אטבוט כמוצר שמשלמים עליו — מה דרוש

### 4.1 פרדוקס השימור (הבעיה המרכזית)
אפליקציות AI ממירות 52% יותר טוב (8.5% מול 5.6% trial-to-paid) ומרוויחות ~40% יותר LTV — אבל churn מהיר ב-30%. שימור שנתי 21.1% (AI) מול 30.7% (לא-AI); refund גבוה ב-20%. **קל לגרום לאנשים לשלם פעם אחת, קשה להחזיק אותם.**

### 4.2 שלושת מניעי ה-churn
1. **Novelty cliff (הרוצח מס' 1):** ה-"wow" הראשון דועך כשהמוצר לא משתלב בשגרה יומית. רוב אפליקציות ה-AI "עשירות בחידוש, עניות בהרגל".
2. **Discovery mindset:** משתמשים מתייחסים לכל מוצר AI כניסוי זמני (מודל/מתחרה חדש כל שבוע).
3. **Value-perception gap:** כשמרגישים שזה "thin wrapper" מעל מודל ציבורי, תמחור פרימיום מרגיש לא מוצדק.

### 4.3 מה מחזיק לקוחות
- **הרגל יומיומי > דמו.** בחר *משימה אחת חוזרת* שגבר עושה הרבה והפוך אותו ל-default עבורה (למשל מכין משהו כל בוקר, או מחזיק משימה חוזרת end-to-end). מטרה: שגבר ייכנס לשגרה תוך שבוע 1, לפני ה-novelty cliff. זה המנוף הכי גדול נגד מספר ה-21%.
- **זיכרון מתמשך בין שיחות (המגן החזק ביותר).** זוכר שם, העדפות, בקשות עבר, הקשר — ומשתמש בזה באופן גלוי ("בפעם הקודמת רצית X, אותו דבר?"). "memory isn't a feature, it's a retention strategy." פרסונליזציה מנתוני משתמש אמיתיים מקצרת time-to-value ב-~30%.
- **מהירות נתפסת.** מתחת ל-1 שנייה שומר flow; כל שנייה נוספת מעלה נטישה ~7%. המדד הקריטי: **TTFT** (time-to-first-token) — streaming שמתחיל מתחת ~600ms מרגיש שיחתי; 2.4s "מרגיש כמו טעינת עמוד מ-2005". יעד: sub-500ms TTFT לצ'אט. streaming הוא ה-win הזול ביותר.
- **Onboarding ל-aha moment.** המסר הראשון = הרושם הראשון; שלוש תכונות מנצחות: ספציפי, מועיל, כן (מצפה ציפיות מדויקות למה הבוט יכול/לא יכול). מפה את הנתיב הכי מהיר לערך אמיתי ראשון והסר כל צעד שלא מוביל אליו.
- **תמחור שעוקב אחרי ערך.** usage-based/hybrid מפחית את טריגר ה"האם אני מקבל תמורה?" שמנויים טהורים יוצרים ל-AI. הגנת churn לא-רצוני: ~28% מהביטולים ב-Google Play הם תשלומים שנכשלו — dunning/retry הוא low-hanging fruit.
- **בידול מעל איכות שיחה בסיסית** (שהגיעה לפריטי בין המודלים). מנצחים על יכולת ספציפית קשה-להעתקה: long context, נתונים בזמן אמת, voice, multimodal, אינטגרציית workflow עמוקה. **גבר כבר כאן** — ביצוע פעולות אמיתיות הוא בידול קשה-להעתקה.

### 4.4 אמון
- **שקיפות שזה AI, לא העמדת פנים של אדם.** 72% נוחים עם צ'אטבוט AI *רק* כשנאמר להם שזה AI. over-humanizing (שמות מזויפים, אמפתיה מזויפת) מזיק. בקליפורניה SB 243 כבר מחייב חוקית גילוי (אוקטובר 2025).
- **הזיות והליכת-ביטחון הורסות אמון.** 75% הוטעו לפחות פעם אחת. עלות אמיתית: Air Canada חויבה בפיצוי על מדיניות החזר שהבוט המציא. RLHF נוטה להפוך מודלים ל-sycophantic (לרצות במקום לדייק) — anti-pattern מובנה שצריך לנטרל אקטיבית.
- **persona consistency = אמון בצורת שפה.** שינוי טון פתאומי גורם למשתמש לפקפק שזה אותו מוצר. מבנה דיאלוג ואופי קבועים בין סשנים/פלטפורמות גם אם ה-UI משתנה.
- **error handling חינני מציל את הקשר.** משתמש שמתאושש מ-fallback ועדיין משלים את המשימה — 50% יותר סיכוי לדרג חיובית גם אחרי בלבול ראשוני. היררכיית degradation: תשובת AI מלאה → מפושטת → מבוססת-כללים → human handoff. אמור "אני לא בטוח, תן לי עוד פרט" במקום תשובה שגויה בביטחון.

---

## 5. רשימת המלצות מתועדפת (P0 / P1 / P2)

> מקרא נגיעה: **[קוד]** הנדסה, **[מוצר]** UX/פיצ'ר, **[שיווק]** מסר/הפצה. מאמץ: S (ימים), M (שבוע-שבועיים), L (חודש+).

### P0 — חובה לפני / סביב launch

| # | המלצה | נוגע | מאמץ |
|---|---|---|---|
| P0-1 | **gate אימות לפני כל "אישור".** extract של `{selectedDate, selectedTime}` מה-DOM ואסרציה מול הצפוי; ללחוץ אישור רק אם תואם. תיקון ישיר ל"אישור על תאריך שגוי". | קוד | S |
| P0-2 | **extract לאימות אחרי כל בחירת תאריך/שעה** (קריאה מה-UI, לא מהקלט, עם Zod). לא תואם → retry/שגיאה, לא להתקדם. הופך כשל שקט לקולני. | קוד | S |
| P0-3 | **scroll-into-view + ודא נראות לפני קליק** (Issue #693), כדי שלא נפעל על אלמנט מחוץ למסך. תיקון ישיר ל"בחירת תאריך שלא נתפסת". | קוד | S |
| P0-4 | **פירוק הזרימה לפעולות אטומיות עם אימות בין כל אחת** (פתח-לוח → ודא-פתוח → בחר-תאריך → ודא → בחר-שעה → ודא → אשר). אין act() רב-שלבי ואין agent חופשי בזרימה קריטית. | קוד | M |
| P0-5 | **observe()→cache→act() בצעדים קריטיים** במקום act() ישיר. בדוק שה-descriptor הוא בדיוק האלמנט הנכון; פותר #1434 ו-#795. | קוד | M |
| P0-6 | **הקול בכל פיקסל — פרסונה אחת חדה** בכל האתר והבוט (hero, כפתורים, אישורים, שגיאות, מיילים). ההעתקה הזולה ביותר עם ההשפעה הגבוהה ביותר מ-Botivation. | מוצר + שיווק | M |
| P0-7 | **מקם נגד הקטגוריה: "לא עוד צ'אטבוט — הוא באמת סוגר".** ביצוע פעולות אמיתיות ככותרת ראשית. הבידול המרכזי שלנו. | שיווק | S |

### P1 — שימור ואמון (מיד אחרי launch)

| # | המלצה | נוגע | מאמץ |
|---|---|---|---|
| P1-1 | **זיכרון מתמשך בין שיחות** (שם, העדפות, בקשות עבר) ושימוש גלוי בו. המגן החזק ביותר נגד churn. | קוד + מוצר | L |
| P1-2 | **הרגל יומיומי:** בחר משימה חוזרת אחת והפוך את גבר ל-default עבורה תוך שבוע 1. המנוף הכי גדול נגד 21% שימור. | מוצר | M |
| P1-3 | **streaming תמיד + יעד sub-500ms TTFT.** לעולם לא spinner ארוך ריק. ה-win הזול ביותר למהירות נתפסת. | קוד | M |
| P1-4 | **היררכיית כשל חיננית** (מלא → מפושט → כללים → handoff). כשלא בטוח — לשאול/להודות, לא לבלף. מציל לקוח (ומונע חבות משפטית — Air Canada). | קוד + מוצר | M |
| P1-5 | **retry עם exponential backoff + timeout פר-צעד + max_retries**, ואחרי N ניסיונות → לוג מובנה (trace id, prompt, selector, screenshot, model version) ועצירה, לא המשך עיוור. | קוד | M |
| P1-6 | **observability:** session replay + trace לכל פעולה; post-mortem שבועי על 10 הכשלים הגרועים. | קוד | M |
| P1-7 | **Social proof שהוא הפצה — "מה גבר סגר השבוע"** (גלריה אנונימית מטושטשת + שיתוף). proof + ויראליות, חזק כי הערך שלנו הוא ביצוע. | מוצר + שיווק | M |
| P1-8 | **שקיפות שזה AI + בלי over-humanizing** (גם חובה חוקית ב-CA). אמון מ-honesty + הצגת נימוק, לא מפרסונה מזויפת. | מוצר | S |
| P1-9 | **onboarding ל-aha moment** עם welcome message ספציפי+מועיל+כן; הסר כל צעד שלא מוביל לערך ראשון. | מוצר | M |

### P2 — צמיחה ואופטימיזציה

| # | המלצה | נוגע | מאמץ |
|---|---|---|---|
| P2-1 | **Hero סביב תירוץ שהמשתמש מזהה את עצמו בו** (רוטציית "תזמין שרברב / תחדש דרכון..."), לא סביב פיצ'רים. | שיווק | S |
| P2-2 | **בחירת ווייב/סגנון תקשורת** ("ישיר וקצר" / "חבר'ה" / "מנומס"). engagement + בקרה, זול (system prompt). | מוצר | S |
| P2-3 | **freemium עם hook + תמחור שקוף בקול המותג** (trial של X משימות שנסגרו, "נעילת מחיר מוקדם"). | מוצר + שיווק | M |
| P2-4 | **ויראליות מובנה במוצר** ("תעביר משימה לחבר" / "תזמין חבר לראות מה גבר סגר"). referral בזרימה. | מוצר | M |
| P2-5 | **DOM mode כברירת מחדל** (לא CUA/vision) למסכים עם DOM; **maxSteps נמוך (8-12)**; timeout שמכליל 30 שניות captcha. חוסך 1-3 שניות וטוקנים לצעד. | קוד | S |
| P2-6 | **תמחור שעוקב אחרי ערך** (hybrid/per-resolution) + הגנת churn לא-רצוני (retry תשלומים, תזכורת חידוש; ~28% מהביטולים = תשלום שנכשל). | מוצר | M |
| P2-7 | **launch של waitlist + PR + לינקדאין** עם זווית "עוזר וואטסאפ ישראלי שבאמת סוגר משימות" (Nexter/mako, startupforstartup). | שיווק | M |
| P2-8 | **instrumentation לשימור מיום 1:** activation rate (% שמגיעים ל-aha), time-to-value, retention D1/D7/D30, turns-to-success, refund reasons. | קוד | M |
| P2-9 | **סשנים ארוכים:** keepAlive:true + reconnect ל-CDP עם backoff; התאם אזור Browserbase לפרוקסי. | קוד | S |
| P2-10 | **anti-sycophancy + grounding:** עגן תשובות factual בretrieval/מקורות, סף ביטחון שמפעיל clarification במקום ניחוש. "אני לא יודע" כפלט מתוכנן ולגיטימי. | קוד | M |

---

## 6. Anti-patterns להימנע מהם

### מ-Stagehand (קוד)
- שילוב כמה פעולות ב-`act()` אחד.
- תיאורי אלמנט מעורפלים ("הכפתור הכחול" במקום "the Sign In button").
- דילוג על אימות תוצאה / הנחה ש-`success:true` = הצלחה אמיתית.
- מתן הוראות ניווט בתוך משימת agent (לנווט בנפרד).
- הנחה ש-DOM יציב בין observe ל-act בלי caching.
- הטמעת סודות בפרומפט (להשתמש ב-`variables`).
- vision/CUA כברירת מחדל כשיש DOM (איטי ויקר מיותר).

### מ-Botivation (מוצר/שיווק)
- **לפתור רק נדנוד ולא ביצוע** — חולשת Botivation; גבר חייב להוכיח ביצוע, אחרת ייתפס כעוד נודניק. הראה outcomes.
- **disclaimer "למטרות בידור ומוטיבציה בלבד"** מחליש אמון — אם גבר באמת מבצע, מקם אותו כאמין/מועיל ולא כגימיק.
- **snark אגרסיבי מדי** — עלול להרתיע קהל רחב; כוונן מינון הומור לקהל היעד.

### מצ'אטבוט-כמוצר (אסטרטגיה)
- **novelty-rich, habit-poor** — מרשים אבל לא חיוני; ייפול ב-novelty cliff.
- **thin wrapper מורגש** — תמחור פרימיום נתפס כלא מוצדק.
- **תשובה שגויה בביטחון** — sycophancy; הורס אמון ועלול לחייב משפטית.
- **over-humanizing** — שמות/אמפתיה מזויפים; backfire.
- **persona מתנדנדת** — קורא כמוצר לא אמין ולא גמור.
- **spinner ארוך ריק** — כל שנייה ~7% נטישה.

---

## מקורות

### Botivation
- https://www.botivation.ai/
- https://www.botivation.ai/assets/index-B2JxT2R4.js
- https://www.mako.co.il/nexter-news/Article-38d9aa031d80c91027.htm
- https://13tv.co.il/item/news/haolam-haboker/season-01/clips/o8dkc-905180971/
- https://13tv.co.il/allshows/4433460/

### Stagehand / Browserbase
- https://www.browserbase.com/blog/stagehand-v3
- https://www.browserbase.com/blog/ai-web-agent-sdk
- https://docs.stagehand.dev/examples/best_practices
- https://github.com/browserbase/stagehand/blob/main/.cursorrules
- https://docs.stagehand.dev/v3/basics/act
- https://docs.stagehand.dev/v3/basics/agent
- https://docs.stagehand.dev/examples/caching
- https://github.com/browserbase/stagehand/issues/693
- https://github.com/browserbase/stagehand/issues/795
- https://github.com/browserbase/stagehand/issues/1434
- https://docs.browserbase.com/introduction/stagehand
- https://docs.browserbase.com/platform/identity/overview
- https://dataresearchtools.com/browserbase-review-2026/
- https://agentmarketcap.ai/blog/2026/04/07/chrome-firefox-native-agent-apis-2026-browser-agentic-primitives
- https://www.capsolver.com/blog/All/browser-use-capsolver
- https://bug0.com/blog/expect-vs-agent-browser-vs-stagehand-vs-passmark
- https://apptad.com/insights/when-your-agent-goes-wrong-a-post-mortem-playbook/
- https://momentic.ai/docs/comparisons/stagehand
- https://www.coronium.io/blog/browserbase-proxy-setup-guide
- https://github.com/browserbase/sdk-node/blob/main/src/resources/sessions/sessions.ts

### צ'אטבוט כמוצר / שימור / אמון
- https://www.creem.io/blog/ai-app-retention-paradox-churn-2026
- https://techcrunch.com/2026/03/10/ai-powered-apps-struggle-with-long-term-retention-new-report-shows/
- https://www.technewsworld.com/story/ai-apps-generate-revenue-but-struggle-with-retention-180236.html
- https://www.contentgrip.com/ai-subscription-apps-retention-problem/
- https://www.bvp.com/atlas/seven-product-strategies-to-prevent-churn-for-b2b-ai-app-leaders
- https://www.useinvent.com/blog/the-cx-leader-s-guide-to-ai-memory-personalization-retention-and-next-gen-chatbots
- https://mem0.ai/blog/ai-chatbot-development-with-persistent-memory
- https://redis.io/blog/how-to-improve-llm-ux-speed-latency-and-caching/
- https://aimultiple.com/llm-latency-benchmark
- https://arxiv.org/html/2604.06183
- https://www.eleken.co/blog-posts/ai-transparency
- https://www.zendesk.com/blog/ai-transparency/
- https://dialzara.com/blog/7-ethical-guidelines-for-building-trustworthy-ai-chatbots
- https://www.neuronux.com/post/ux-design-for-conversational-ai-and-chatbots
- https://clearly.design/articles/ai-design-4-designing-for-ai-failures
- https://www.aiuxdesign.guide/patterns/error-recovery
- https://articles.chatnexus.io/knowledge-base/handling-chatbot-failures-gracefully-when-ai-doesn/
- https://www.chameleon.io/blog/successful-user-onboarding
- https://www.appcues.com/blog/aha-moment-guide
- https://blog.fastbots.ai/ai-chatbot-pricing-comparison-what-businesses-actually-pay-in-2026/
- https://stammer.ai/post/chatbot-pricing-models
- https://mitsloanedtech.mit.edu/ai/basics/addressing-ai-hallucinations-and-bias/
- https://alhena.ai/blog/chatbot-hallucination/
- https://blog.fastbots.ai/12-chatbot-best-practices-to-boost-engagement-and-roi-in-2026/
- https://www.myaifrontdesk.com/blogs/ai-chatbot-free-vs-paid-services-unpacking-the-real-value-and-differences
