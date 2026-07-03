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


def _build_task(job: dict) -> str:
    # נווט אוטונומי — לא מתכון דטרמיניסטי. נותנים מטרה + עובדות + חוקי ברזל, והוא
    # מבין את המסך לבד. ה-task פלטפורמה-אגנוסטי (Ontopo / Tabit / אתר אחר) — אל
    # תקודד פה שמות כפתורים או רצף קבוע. ה-markers (SUMMARY_REACHED/CARD_REQUIRED/
    # BOOKED/MISSING) הם החוזה עם _parse_result — אותם תמיד לדווח בדיוק.
    plat = f" (מערכת {job['platform']})" if job.get("platform") else ""
    steps = f"""
המשימה: להזמין שולחן ל-{job["party_size"]} סועדים בתאריך {job["date"]} בשעה {job["time"]}.
התחל מהכתובת: {job["url"]} (דף הזמנות מקום של המסעדה, בעברית{plat}).

אתה נווט אוטונומי. האתר יכול להיות Ontopo, Tabit, או מערכת אחרת, וה-UI משתנה
ביניהם — אל תחפש רצף כפתורים קבוע. הבן כל מסך ופעל לפי העקרונות:
- בחר את מספר הסועדים, התאריך והשעה המבוקשים. אם השעה המדויקת תפוסה — בחר את
  הזמינה הקרובה ביותר, עד 30 דקות הפרש לכל היותר (קדימה או אחורה). אין זמינות
  בטווח הזה → FAILED:no_availability.
- התקדם דרך כל שלבי ההזמנה (חיפוש שולחן, בחירת מועד, אישור תנאים וכו') עד שתגיע
  ל*מסך הסיכום* — המסך שמרכז את כל פרטי ההזמנה ממש לפני האישור/תשלום הסופי.
- באנר עוגיות/פרסומת — סגור והמשך. אלמנט שלא מגיב ללחיצה — נסה מקלדת (Tab/Enter)
  או גלול אליו; חזרת על אותה פעולה פעמיים בלי שינוי במסך — שנה גישה (חזור אחורה
  ונסה נתיב אחר) במקום לנסות שוב.
- אינך מצליח להתקדם בכלל (דף שבור, נדרשת התחברות או קוד SMS) — עצור וסיים את
  הדיווח ב-FAILED:<סיבה קצרה באנגלית> (למשל FAILED:login_required).

*** חוק ברזל — פרטי לקוח והחלטות: השתמש *רק* בשם/אימייל/טלפון שניתנו בדיוק כאן
למטה. אסור להמציא או לנחש שום ערך (שם, מייל, שם משפחה). אם שדה חובה בטופס ריק
ואין לך אותו — אל תמלא ואל תמציא; עצור מיד וסיים את הדיווח במילה MISSING ואחריה
שם השדה, תמיד באנגלית: MISSING:name / MISSING:last_name / MISSING:email /
MISSING:phone. אותו כלל לבחירות שהאתר כופה ולא קיבלת עליהן העדפה — אזור ישיבה
(פנים/בחוץ/בר), סוג תפריט, וכדומה: לעולם אל תבחר בשביל הלקוח; עצור ודווח
MISSING:<שם הבחירה באנגלית>, למשל MISSING:seating_area. חריג יחיד: אם יש רק
אפשרות אחת זמינה — קח אותה והמשך. ***
פרטי קשר: שם "{job.get("name") or ""}", אימייל "{job.get("email") or ""}", טלפון "{job.get("phone") or ""}".

בסוף הדיווח ציין מה נבחר בפועל (תאריך, שעה, מספר סועדים), ואז את שורת הסיום —
תמיד השורה האחרונה של הדיווח, באותיות גדולות בדיוק:
SUMMARY_REACHED / CARD_REQUIRED / BOOKED <אישור> / MISSING:<שדה> / FAILED:<סיבה>.
אל תשתמש במילים האלה בשום מקום אחר בדיווח.
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
הוסף גם את המילה CARD_REQUIRED."""
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
    last = next((ln for ln in reversed(final.splitlines()) if ln.strip()), "")
    card = "CARD_REQUIRED" in last
    missing = _marker_arg(last, "MISSING:") if "MISSING:" in last else ""
    failed = _marker_arg(last, "FAILED:") if "FAILED:" in last else ""
    # השעה שנבחרה בפועל (החוזה: אחרי SUMMARY_REACHED) — כדי שגבר יציע חלופה ללקוח
    # ("יש 21:00 במקום 20:30, מתאים?") לפני הסגירה, וה-commit יסגור את מה שאושר.
    m = re.search(r"\b(\d{1,2}:\d{2})\b", last)
    chosen_time = m.group(1) if m else ""
    if commit:
        # BOOKED <אישור> = נסגר באמת; כרטיס/שדה-חסר/כישלון גוברים — לא נרשמת הזמנה.
        booked = "BOOKED" in last and not card and not missing and not failed
        confirmation = ""
        if booked:
            confirmation = last[last.find("BOOKED") + len("BOOKED") :].strip(" :–-")[:120]
        return {
            "success": booked,
            "stage": final[:400],
            "card_required": card,
            "booked": booked,
            "confirmation": confirmation,
            "missing": missing,
            "failed": failed,
            "time": chosen_time,
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
        "message": final,
    }


async def _run(job: dict) -> dict:
    from browser_use import Agent, BrowserProfile
    from browser_use.llm import ChatGoogle

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if key:
        os.environ["GOOGLE_API_KEY"] = key
        os.environ["GEMINI_API_KEY"] = key

    profile_kwargs: dict = {"headless": job.get("headless", True)}
    if job.get("cdp_url"):  # browserbase / remote — stealth+captcha חיים שם
        profile_kwargs["cdp_url"] = job["cdp_url"]
    elif job.get("chrome_path"):  # local dev
        profile_kwargs["executable_path"] = job["chrome_path"]
    rec = job.get("record_dir")
    if rec:
        os.makedirs(rec, exist_ok=True)
        profile_kwargs["record_video_dir"] = rec

    profile = BrowserProfile(**profile_kwargs)
    llm = ChatGoogle(model=job.get("model") or "gemini-3-flash-preview")
    agent_kwargs: dict = {"task": _build_task(job), "llm": llm, "browser_profile": profile}
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
