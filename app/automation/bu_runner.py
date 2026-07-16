"""bu_runner — נוהג הזמנת מסעדה (Ontopo/Tabit) דרך browser-use agent (ניווט אוטונומי).

רץ ב-.venv-bu בלבד (browser-use מצמיד google-genai==1.65, מתנגש עם ה-app שעל 2.8),
ולכן הקובץ הזה מייבא *רק* browser_use + stdlib — לעולם לא app.*. מופעל כ-subprocess:
    .venv-bu/bin/python app/automation/bu_runner.py   < job.json

קלט: JSON job ב-stdin. פלט: כותב JSON תוצאה ל-job["result_path"] (נקי, בלי ערבוב עם
ה-logs הרועשים של browser-use ב-stdout/stderr).

שני מצבים לפי job["dry_run"]:
  dry_run=True  → recon: עוצרים ב*מסך הסיכום*, לפני האישור הסופי (לא סוגרים, גם אם
                  אין כרטיס). מדווח SUMMARY_REACHED (+ CARD_REQUIRED אם נדרש כרטיס).
  dry_run=False → commit: סוגרים באמת — *אבל* אם נדרש כרטיס אשראי עוצרים שם תמיד
                  (PCI: לא מזינים כרטיס). מקום בלי-כרטיס נסגר; מדווח BOOKED <אישור>.
"""

import asyncio
import json
import os
import re
import sys


def _notes_line(job: dict) -> str:
    """העדפות שהלקוח נתן (אזור ישיבה, אירוע) — סוגרות בחירות שאחרת היו עוצרות ב-MISSING."""
    n = (job.get("notes") or "").strip()
    return (
        f'\nהעדפות מהלקוח: "{n}" — כבד אותן בבחירות שהאתר מציע. העדפה עם צורך מאחוריה '
        "(מעשנים, נגישות, עגלה) גוברת על הניסוח: אם יש אופציה שעונה על הצורך במדויק "
        '(למשל "אזור מעשנים") — בחר אותה גם כשהלקוח ניסח כללי ("בחוץ").'
        if n
        else ""
    )


def _build_task(job: dict) -> str:
    # נווט אוטונומי — לא מתכון דטרמיניסטי. נותנים מטרה + עובדות + חוקי ברזל, והוא
    # מבין את המסך לבד. ה-task פלטפורמה-אגנוסטי (Ontopo / Tabit / אתר אחר) — אל
    # תקודד פה שמות כפתורים או רצף קבוע. ה-markers (SUMMARY_REACHED/CARD_REQUIRED/
    # BOOKED/MISSING) הם החוזה עם _parse_result — אותם תמיד לדווח בדיוק.
    plat = f" (מערכת {job['platform']})" if job.get("platform") else ""
    # חוק השעה — שתי רמות: לקוח גמיש (אמר "בסביבות"/"גמיש") מקבל חלון ±60 בלי
    # עצירה; ברירת המחדל נשארת ±30 + הצעת חלופות. בשתיהן ההחלטה חד-פעמית ומהירה.
    if job.get("time_flex"):
        time_rule = (
            "הלקוח גמיש בשעה: אם המבוקשת לא זמינה — קח את הזמינה הקרובה ביותר, עד "
            "60 דקות הפרש (קדימה או אחורה), בלי לעצור ולשאול; ציין בדיווח את השעה "
            "שנבחרה בפועל. אין אף שעה גם בטווח הזה אבל יש פנויות אחרות באותו יום → "
            "עצור עם MISSING:time ושורת OPTIONS: עם השעות הפנויות (עד 8, מופרדות "
            "ב-|). אין אף שעה פנויה באותו יום → FAILED:no_availability."
        )
    else:
        time_rule = (
            "רק אם המבוקשת באמת לא מופיעה או מסומנת תפוסה — הזמינה הקרובה ביותר, "
            "עד 30 דקות הפרש לכל היותר (קדימה או אחורה). אין זמינות גם בטווח הזה "
            "אבל הדף כן מציג שעות פנויות אחרות באותו יום → אל תבחר בשביל הלקוח "
            "ואל תדווח כישלון: עצור עם MISSING:time, ובשורה שלפני שורת הסיום "
            "OPTIONS: עם השעות הפנויות בדיוק כפי שהן מוצגות בדף (עד 8 הקרובות "
            "למבוקשת), מופרדות ב-|, למשל: OPTIONS: 18:45 | 19:30 | 21:15. "
            "אין אף שעה פנויה באותו יום → FAILED:no_availability."
        )
    time_rule += (
        " ההחלטה הזאת מיידית: קריאה אחת של לוח הזמינות מכריעה. אסור 'לחפש' את "
        "השעה המבוקשת דרך אזורי ישיבה, מסלולים או ניסיונות חוזרים — אין אותה "
        "בלוח? פעל לפי החוק הזה מיד, בצעד אחד."
    )
    if job.get("resume"):
        # pause-resume: הדפדפן פתוח בדיוק במסך שבו הריצה הקודמת עצרה (MISSING) —
        # ממשיכים משם עם הפרטים שהלקוח השלים, בלי לנווט מחדש.
        intro = f"""
אתה ממשיך הזמנת שולחן ל-{job["party_size"]} סועדים בתאריך {job["date"]} בשעה {job["time"]}
שכבר התחלת קודם. הדפדפן פתוח בדיוק במסך שבו עצרת — המשך מהמסך הנוכחי. אל תנווט
לכתובת אחרת ואל תתחיל את התהליך מההתחלה.
מה שקרה עד כה: {job["resume"].get("recap") or ""}
עצרת כי חסר פרט מהלקוח — הוא השלים אותו עכשיו, והפרטים המעודכנים מופיעים למטה."""
    else:
        intro = f"""
המשימה: להזמין שולחן ל-{job["party_size"]} סועדים בתאריך {job["date"]} בשעה {job["time"]}.
התחל מהכתובת: {job["url"]} (דף הזמנות מקום של המסעדה, בעברית{plat})."""
    steps = f"""{intro}

אתה נווט אוטונומי. האתר יכול להיות Ontopo, Tabit, או מערכת אחרת, וה-UI משתנה
ביניהם — אל תחפש רצף כפתורים קבוע. הבן כל מסך ופעל לפי העקרונות:
- בחר את מספר הסועדים, התאריך והשעה המבוקשים. השעה המבוקשת קודמת לכל: אם היא
  מוצגת כזמינה — חובה לבחור בדיוק אותה, אסור לקחת שעה אחרת כשהמבוקשת קיימת.
  אחרי הבחירה ודא שמה שנבחר בפועל הוא אכן השעה המבוקשת — לא, תקן לפני שתמשיך.
  {time_rule}
- התקדם דרך כל שלבי ההזמנה (חיפוש שולחן, בחירת מועד, אישור תנאים וכו') עד שתגיע
  ל*מסך הסיכום* — המסך שמרכז את כל פרטי ההזמנה ממש לפני האישור/תשלום הסופי.
- באנר עוגיות/פרסומת — סגור והמשך. אלמנט שלא מגיב ללחיצה — נסה מקלדת (Tab/Enter)
  או גלול אליו; חזרת על אותה פעולה פעמיים בלי שינוי במסך — שנה גישה (חזור אחורה
  ונסה נתיב אחר) במקום לנסות שוב.
- עבוד רק מול האתר שקיבלת. אסור לפתוח מנוע חיפוש (גוגל/DDG וכדומה) או לנחש
  כתובות אחרות כדי "למצוא" את המסעדה — כתובת היעד היא זו שבמשימה, במלואה, גם
  אם היא מוצגת על המסך מקוצרת (עם ...). דף שגיאת שרת (503/500 או דף שגיאה של
  CDN) — רענן פעם אחת בלבד; עדיין שגיאה → FAILED:broken_page מיד, בלי חיפושים.
- אינך מצליח להתקדם — אל תדווח כישלון עיוור: קודם תבין מה הבעיה מקריאת הדף עצמו
  (כתוב שהמקום סגור? אין הזמנות אונליין? מלא במועד הזה? דורש התחברות?). בחר את
  הסיבה המדויקת: FAILED:no_availability (אין מקום פנוי במועד) / FAILED:closed
  (המקום סגור או לא פעיל) / FAILED:no_online_booking (לא מקבלים הזמנות באתר) /
  FAILED:login_required / FAILED:broken_page. בשורה שלפני שורת הסיום כתוב
  בעברית מה בדיוק ראית בדף.

*** חוק ברזל — פרטי לקוח והחלטות: השתמש *רק* בשם/אימייל/טלפון שניתנו בדיוק כאן
למטה. אסור להמציא או לנחש שום ערך (שם, מייל, שם משפחה). אם שדה חובה בטופס ריק
ואין לך אותו — אל תמלא ואל תמציא; עצור מיד וסיים את הדיווח במילה MISSING ואחריה
שם השדה, תמיד באנגלית: MISSING:name / MISSING:last_name / MISSING:email /
MISSING:phone. אותו כלל לבחירות שהאתר כופה ולא קיבלת עליהן העדפה — אזור ישיבה
(פנים/בחוץ/בר), סוג תפריט, וכדומה: לעולם אל תבחר בשביל הלקוח, וגם ברירת מחדל
שכבר מסומנת בטופס היא בחירה כזאת — אל תשאיר אותה סתם, עצור ודווח
MISSING:<שם הבחירה באנגלית>, למשל MISSING:seating_area. כשאתה עוצר על בחירה
כזאת, הוסף בשורה שלפני שורת הסיום שורה שמתחילה ב-OPTIONS: עם האפשרויות בדיוק
כפי שהן מופיעות בדף, מופרדות ב-|, למשל: OPTIONS: בפנים | בר גבוה | מרפסת מעשנים.
חריג יחיד: כשקיימת באמת רק אפשרות אחת — קח אותה והמשך.
קיבלת העדפה מהלקוח אבל היא לא תואמת חד-משמעית אף אפשרות בדף (למשל "בר" מול
כמה סוגי בר) — אל תתלבט בניסיונות חוזרים: אם אחת קרובה בבירור בחר אותה,
ואחרת עצור מיד עם MISSING ושורת OPTIONS. ***
פרטי קשר: שם "{job.get("name") or ""}", אימייל "{job.get("email") or ""}", טלפון "{job.get("phone") or ""}".{_notes_line(job)}

ראית בדף פרט ששווה ללקוח לדעת — הנחה, מבצע, הגבלת זמן שולחן, דרישת הגעה בזמן?
הוסף שורה נפרדת שמתחילה ב-PERK: ואחריה תיאור קצר בעברית (למשל
PERK: 10% הנחה על התפריט בשעה הזאת). אין — אל תוסיף.

סימנת בדרך צ'קבוקסים של הסכמה (תקנון, מדיניות ביטול, תנאי אזור ישיבה, הגבלת
זמן)? הוסף שורה נפרדת שמתחילה ב-AGREED: עם תמצית קצרה בעברית של כל מה שאושר,
מופרד ב-|, למשל: AGREED: תקנון ומדיניות ביטול | האזור בחוץ הוא אזור עישון.
תמצית בלבד, לא ציטוט הנוסח המלא. לא סימנת שום הסכמה — אל תוסיף את השורה.

בסוף הדיווח ציין מה נבחר בפועל (תאריך, שעה, מספר סועדים), ואז את שורת הסיום —
תמיד השורה האחרונה של הדיווח, באותיות גדולות בדיוק:
SUMMARY_REACHED / CARD_REQUIRED / BOOKED <אישור> / MISSING:<שדה> / FAILED:<סיבה>.
שורת סיום אחת ויחידה: אם כמה מצבים נכונים יחד (הגעת לסיכום *וגם* נדרש כרטיס) —
כתוב את שניהם באותה שורה אחת (SUMMARY_REACHED 19:00 CARD_REQUIRED), לא בשורות
נפרדות. אל תשתמש במילים האלה בשום מקום אחר בדיווח.
"""
    # dry_run=True → recon: עוצרים במסך הסיכום *לפני* האישור הסופי (לא סוגרים, גם בלי כרטיס).
    # commit (dry_run=False) → סוגרים באמת, אבל אם נדרש כרטיס אשראי עוצרים שם (PCI).
    if job.get("dry_run", True):
        tail = """
*** חוק ברזל: עצור ב*מסך הסיכום*, *לפני* הכפתור הסופי. לעולם אל תלחץ על כפתור
הסיום ("אשר הזמנה" / "סיום" / "הזמן" / "שלם" וכדומה), ואל תזין פרטי כרטיס אשראי —
בין אם נדרש כרטיס ובין אם לא. המטרה היא רק להגיע עד מסך הסיכום, *בלי* לסגור. ***

כשהגעת למסך הסיכום, סיים את הדיווח במילה SUMMARY_REACHED ואחריה השעה שנבחרה
בפועל (למשל: SUMMARY_REACHED 21:00). אם המסך דורש פרטי כרטיס אשראי כדי לסיים —
הוסף גם את המילה CARD_REQUIRED, ובשורה שלפני שורת הסיום הוסף:
URL: <הכתובת המלאה שבשורת הכתובת של הדפדפן עכשיו> — כדי שהלקוח יקבל לינק
שמחזיר אותו בדיוק לנקודה שבה עצרת, לא לדף ההתחלה."""
    else:
        tail = """
*** חוק ברזל — כרטיס אשראי: אם בשלב כלשהו האתר דורש פרטי כרטיס אשראי / תשלום מראש,
עצור מיד. אל תזין שום פרטי כרטיס ואל תמשיך — מקום שדורש תשלום מראש לא נסגר אוטומטית.
במקרה כזה סיים את הדיווח במילה: CARD_REQUIRED ***

אם לא נדרש כרטיס אשראי: לחץ על כפתור האישור הסופי לסגירת ההזמנה ("אשר הזמנה" /
"סיום" / "הזמן" וכדומה). ודא שמופיע מסך/הודעת אישור שההזמנה נסגרה. רק כשההזמנה
נסגרה בהצלחה — סיים את הדיווח במילה BOOKED ואחריה מספר האישור אם הופיע."""
    return steps + tail


def _marker_arg(line: str, marker: str) -> str:
    """הטקסט שאחרי marker בשורת הסיום ('MISSING:email' → 'email'). ריק-בטוח."""
    parts = line[line.find(marker) + len(marker) :].strip(" :–-").split()
    return parts[0].rstrip(".,") if parts else "unknown"


def _parse_result(final: str, *, commit: bool) -> dict:
    """דיווח ה-agent → תוצאת JSON. הנתיב הבטיחותי: markers נקראים *רק* מהשורה האחרונה
    ו-case-sensitive (החוזה ב-task: שורת סיום באותיות גדולות) — פרוזה כמו "fully booked"
    או "לא נדרש כרטיס" לא מדליקה כלום. בסגירה (commit) success=True רק אם באמת נסגר
    (BOOKED). ב-recon הצלחה = SUMMARY_REACHED בלי סגירה. MISSING:<שדה> = שדה חובה ריק →
    כישלון + השדה ב-details. FAILED:<סיבה> = לא הצליח להתקדם (אין זמינות/login/דף שבור)."""
    final = (final or "").strip()
    lines = [ln for ln in final.splitlines() if ln.strip()]
    # בלוק הסיום = עד 3 השורות האחרונות, לא רק האחרונה: ה-agent לפעמים מפצל את
    # שורת הסיום ("SUMMARY_REACHED 19:00" ואז "CARD_REQUIRED" בשורה נפרדת) —
    # נצפה חי פעמיים ב-15.7: ריצה שהגיעה למסך האשראי דווחה ללקוח ככישלון.
    # ה-markers עדיין case-sensitive באותיות גדולות בלבד, אז פרוזה לא מדליקה כלום.
    # חריג בטיחותי: BOOKED (רישום הזמנה אמיתית) נקרא רק מהשורה האחרונה ממש —
    # מרקר-הזמנה באמצע דיווח לעולם לא רושם הזמנה פנטום (הגנת R1 נשארת קשיחה).
    last = " ".join(lines[-3:])
    strict_last = lines[-1] if lines else ""
    # דפדפן שמת באמצע (CDP נפל, timeout של LLM) משאיר דיווח ריק — שם מפורש במקום
    # כישלון אילם (אוחד משני ענפי הוורטיקלים; נצפה חי 15.7 גם בהופעות וגם בביטוח).
    empty_report = not lines
    card = "CARD_REQUIRED" in last
    missing = _marker_arg(last, "MISSING:") if "MISSING:" in last else ""
    failed = _marker_arg(last, "FAILED:") if "FAILED:" in last else ""
    if empty_report:
        failed = "browser_error"
    # השעה שנבחרה בפועל (החוזה: אחרי SUMMARY_REACHED) — כדי שגבר יציע חלופה ללקוח
    # ("יש 21:00 במקום 20:30, מתאים?") לפני הסגירה, וה-commit יסגור את מה שאושר.
    m = re.search(r"\b(\d{1,2}:\d{2})\b", last)
    chosen_time = m.group(1) if m else ""
    # PERK: פרטים ששווים ללקוח (הנחה/מבצע/מגבלה) שה-agent ראה בדף — עוברים להודעה.
    perks = [
        ln.split("PERK:", 1)[1].strip().replace("[", "").replace("]", "")[:120]
        for ln in final.splitlines()
        if "PERK:" in ln
    ]
    perk = " · ".join(p for p in perks if p)[:200]
    # OPTIONS: האפשרויות האמיתיות מהדף כשעוצרים על בחירה כפויה (MISSING) — גבר
    # מציג אותן ללקוח כרשימת בחירה במקום שאלה גנרית ("בפנים/בחוץ/בר").
    options: list = []
    for ln in final.splitlines():
        if ln.strip().startswith("OPTIONS:"):
            options = [o.strip()[:60] for o in ln.split("OPTIONS:", 1)[1].split("|") if o.strip()]
    options = options[:10]
    # AGREED: תמצית הצ'קבוקסים שה-agent אישר בשם הלקוח — גבר מגלה אותם בהודעת
    # הסיום ("אישרתי בשמך: תקנון...") במקום שהסכמות ייחתמו בשקט (בקשת אלון 15.7).
    agreed: list = []
    for ln in final.splitlines():
        if ln.strip().startswith("AGREED:"):
            agreed = [
                a.strip().replace("[", "").replace("]", "")[:80]
                for a in ln.split("AGREED:", 1)[1].split("|")
                if a.strip()
            ]
    agreed = agreed[:5]
    # URL: הכתובת שבה הדפדפן עצר (קיר כרטיס) — לינק שמחזיר את הלקוח לנקודת העצירה.
    page_now = ""
    for ln in final.splitlines():
        if ln.strip().startswith("URL:"):
            page_now = ln.strip()[4:].strip()[:300]
    if commit:
        # BOOKED <אישור> = נסגר באמת; כרטיס/שדה-חסר/כישלון גוברים — לא נרשמת הזמנה.
        booked = "BOOKED" in strict_last and not card and not missing and not failed
        confirmation = ""
        if booked:
            confirmation = strict_last[strict_last.find("BOOKED") + len("BOOKED") :].strip(" :–-")[
                :120
            ]
        return {
            "success": booked,
            "stage": final[:400],
            "card_required": card,
            "booked": booked,
            "confirmation": confirmation,
            "missing": missing,
            "failed": failed,
            "time": chosen_time,
            "perk": perk,
            "options": options,
            "agreed": agreed,
            "page_now": page_now,
            "message": final,
        }
    # recon (dry_run): הצלחה = הגענו למסך הסיכום (SUMMARY_REACHED), בלי סגירה אמיתית.
    summary_reached = "SUMMARY_REACHED" in last
    return {
        "success": summary_reached and not missing and not failed,
        "stage": final[:400],
        "card_required": card,
        "booked": False,
        "confirmation": "",
        "summary_reached": summary_reached,
        "missing": missing,
        "failed": failed,
        "time": chosen_time,
        "perk": perk,
        "options": options,
        "agreed": agreed,
        "page_now": page_now,
        "message": final,
    }


def _profile_kwargs(job: dict) -> dict:
    kwargs: dict = {"headless": job.get("headless", True)}
    if job.get("cdp_url"):  # browserbase / remote — stealth+captcha חיים שם
        kwargs["cdp_url"] = job["cdp_url"]
        # ה-keepAlive של Browserbase מגן רק מפני *ניתוק*; בלעדי keep_alive כאן
        # browser-use סוגר את הדפדפן בסוף הריצה (Browser.close) והורג את הסשן
        # שה-pause-resume צריך חי. השחרור בפועל: release_session בכל נתיב סיום + sweeper.
        kwargs["keep_alive"] = True
    elif job.get("chrome_path"):  # local dev — בלי keep_alive, שלא יישאר Chrome תלוי
        kwargs["executable_path"] = job["chrome_path"]
    if job.get("record_dir"):
        kwargs["record_video_dir"] = job["record_dir"]
    return kwargs


async def _run(job: dict) -> dict:
    from browser_use import Agent, BrowserProfile
    from browser_use.llm import ChatGoogle

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if key:
        os.environ["GOOGLE_API_KEY"] = key
        os.environ["GEMINI_API_KEY"] = key

    rec = job.get("record_dir")
    if rec:
        os.makedirs(rec, exist_ok=True)

    profile = BrowserProfile(**_profile_kwargs(job))
    # בלי fallback מקודד — המודל מגיע תמיד מה-job (settings.model_name); שם מיושן
    # כאן היה נשלף בשקט בדיבוג ידני ומסתיר את הקונפיגורציה האמיתית.
    llm = ChatGoogle(model=job["model"])
    agent_kwargs: dict = {
        "task": _build_task(job),
        "llm": llm,
        "browser_profile": profile,
        # דגלי מהירות — A/B חי מול Ontopo (poc/spike_speed.py, 15.7.26): ‎~34%‎ פחות זמן
        # ריצה, זמן-לצעד ירד מ-24-35 שנ' ל-17.5 שנ', אותה איכות עצירה (MISSING נכון,
        # פרטים נכונים, בלי לופים, PERK עדיין מדווח).
        # flash_mode: משמיט thinking/evaluation_previous_goal/next_goal/planning מסכמת
        # הפלט של כל צעד (prompt מערכת קצר יותר) — פחות טוקנים = צעד מהיר יותר.
        "flash_mode": True,
        # use_judge=False: מדלג על קריאת LLM-שופט נוספת בסוף הריצה — ה-markers של
        # _parse_result הם השופט שלנו ממילא.
        "use_judge": False,
    }
    if job.get("resume"):
        # ברירת המחדל של browser-use מנווטת אוטומטית לכל URL שמופיע ב-task —
        # ב-resume זה היה הורס את המסך הקפוא. חובה לכבות.
        agent_kwargs["directly_open_url"] = False
    if rec:  # הקלטה: GIF + הנמקת ה-agent צעד-צעד, לניתוח אחר כך
        agent_kwargs["generate_gif"] = os.path.join(rec, "run.gif")
        agent_kwargs["save_conversation_path"] = os.path.join(rec, "conversation")

    agent = Agent(**agent_kwargs)
    history = await agent.run(max_steps=job.get("max_steps", 40))
    final = (history.final_result() or "").strip()
    return _parse_result(final, commit=not job.get("dry_run", True))


def main() -> None:
    job = json.load(sys.stdin)
    try:
        result = asyncio.run(_run(job))
    except Exception as e:  # noqa: BLE001 — כל כשל הופך לתוצאה כנה, לא ל-traceback אילם
        result = {
            "success": False,
            "stage": "error",
            "card_required": False,
            "message": f"{type(e).__name__}: {e}",
        }
    with open(job["result_path"], "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
