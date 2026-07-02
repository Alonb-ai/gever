"""bu_runner — נוהג הזמנת מסעדה ב-Ontopo דרך browser-use agent (ניווט אוטונומי).

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
import sys


def _build_task(job: dict) -> str:
    # נווט אוטונומי — לא מתכון דטרמיניסטי. נותנים מטרה + עובדות + חוקי ברזל, והוא
    # מבין את המסך לבד. ה-task פלטפורמה-אגנוסטי (Ontopo / Tabit / אתר אחר) — אל
    # תקודד פה שמות כפתורים או רצף קבוע. ה-markers (SUMMARY_REACHED/CARD_REQUIRED/
    # BOOKED/MISSING) הם החוזה עם _parse_result — אותם תמיד לדווח בדיוק.
    steps = f"""
המשימה: להזמין שולחן ל-{job["party_size"]} סועדים בתאריך {job["date"]} בשעה {job["time"]}.
התחל מהכתובת: {job["url"]} (דף הזמנות מקום של המסעדה, בעברית).

אתה נווט אוטונומי. האתר יכול להיות Ontopo, Tabit, או מערכת אחרת, וה-UI משתנה
ביניהם — אל תחפש רצף כפתורים קבוע. הבן כל מסך ופעל לפי העקרונות:
- בחר את מספר הסועדים, התאריך והשעה המבוקשים. אם השעה המדויקת תפוסה — בחר את
  הזמינה הקרובה ביותר.
- התקדם דרך כל שלבי ההזמנה (חיפוש שולחן, בחירת מועד, אישור תנאים וכו') עד שתגיע
  ל*מסך הסיכום* — המסך שמרכז את כל פרטי ההזמנה ממש לפני האישור/תשלום הסופי.

*** חוק ברזל — פרטי לקוח: השתמש *רק* בשם/אימייל/טלפון שניתנו בדיוק כאן למטה. אסור
להמציא או לנחש שום ערך (שם, מייל, שם משפחה). אם שדה חובה בטופס ריק ואין לך אותו —
אל תמלא ואל תמציא; עצור מיד וסיים את הדיווח במילה MISSING ואחריה שם השדה
(למשל MISSING:email או MISSING:name). ***
פרטי קשר: שם "{job.get("name") or ""}", אימייל "{job.get("email") or ""}", טלפון "{job.get("phone") or ""}".
"""
    # dry_run=True → recon: עוצרים במסך הסיכום *לפני* האישור הסופי (לא סוגרים, גם בלי כרטיס).
    # commit (dry_run=False) → סוגרים באמת, אבל אם נדרש כרטיס אשראי עוצרים שם (PCI).
    if job.get("dry_run", True):
        tail = """
*** חוק ברזל: עצור ב*מסך הסיכום*, *לפני* הכפתור הסופי. לעולם אל תלחץ על כפתור
הסיום ("אשר הזמנה" / "סיום" / "הזמן" / "שלם" וכדומה), ואל תזין פרטי כרטיס אשראי —
בין אם נדרש כרטיס ובין אם לא. המטרה היא רק להגיע עד מסך הסיכום, *בלי* לסגור. ***

כשהגעת למסך הסיכום, סיים את הדיווח במילה SUMMARY_REACHED. אם המסך דורש פרטי כרטיס
אשראי כדי לסיים — הוסף אחריה גם את המילה CARD_REQUIRED."""
    else:
        tail = """
*** חוק ברזל — כרטיס אשראי: אם בשלב כלשהו האתר דורש פרטי כרטיס אשראי / תשלום מראש,
עצור מיד. אל תזין שום פרטי כרטיס ואל תמשיך — מקום שדורש תשלום מראש לא נסגר אוטומטית.
במקרה כזה סיים את הדיווח במילה: CARD_REQUIRED ***

אם לא נדרש כרטיס אשראי: לחץ על כפתור האישור הסופי לסגירת ההזמנה ("אשר הזמנה" /
"סיום" / "הזמן" וכדומה). ודא שמופיע מסך/הודעת אישור שההזמנה נסגרה. רק כשההזמנה
נסגרה בהצלחה — סיים את הדיווח במילה BOOKED ואחריה מספר האישור אם הופיע."""
    return steps + tail


def _parse_result(final: str, *, commit: bool) -> dict:
    """דיווח ה-agent → תוצאת JSON. הנתיב הבטיחותי: כרטיס מזוהה *רק* לפי ה-marker המפורש
    CARD_REQUIRED (לא לפי substring עברי שתופס גם שלילה). בסגירה (commit) success=True רק
    אם באמת נסגר (BOOKED). ב-recon הצלחה = הגענו למסך הסיכום (SUMMARY_REACHED), בלי סגירה.
    בכל מצב: MISSING:<field> = שדה חובה ריק → כישלון + השדה החסר ב-details."""
    final = (final or "").strip()
    low = final.lower()
    # marker מפורש בלבד — שלילה עברית ("לא נדרש כרטיס") לא מדליקה אותו.
    card = "card_required" in low
    missing = ""
    if "missing:" in low:
        missing = final[low.find("missing:") + len("missing:") :].strip(" :–-\n").split()[0]
    if commit:
        # markers מה-task: BOOKED <אישור> = נסגר באמת, CARD_REQUIRED = קיר כרטיס (לא נסגר).
        booked = ("booked" in low) and not card and not missing
        confirmation = ""
        if booked:
            confirmation = final[low.find("booked") + len("booked") :].strip(" :–-\n")[:120]
        return {
            "success": booked,  # נעצר בכרטיס/נתקע/חסר שדה → לא הזמנה, לא נרשום
            "stage": final[:400],
            "card_required": card,
            "booked": booked,
            "confirmation": confirmation,
            "missing": missing,
            "message": final,
        }
    # recon (dry_run): הצלחה = הגענו למסך הסיכום (SUMMARY_REACHED), בלי סגירה אמיתית.
    # שדה חובה חסר (MISSING:<field>) גובר → כישלון, גבר ישאל את הלקוח.
    summary_reached = "summary_reached" in low
    return {
        "success": summary_reached and not missing,
        "stage": final[:400],
        "card_required": card,
        "booked": False,
        "confirmation": "",
        "summary_reached": summary_reached,
        "missing": missing,
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
