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
    steps = f"""
לך לכתובת {job["url"]} (אתר הזמנות מסעדה Ontopo, בעברית).
המטרה: להזמין שולחן ל-{job["party_size"]} אנשים בתאריך {job["date"]} בשעה {job["time"]}.

*** חוק ברזל — פרטי לקוח: השתמש *רק* בשם/אימייל/טלפון שניתנו בדיוק כאן למטה. אסור
להמציא או לנחש שום ערך (שם, מייל, שם משפחה). אם שדה חובה בטופס ריק ואין לך אותו —
אל תמלא אותו ואל תמציא; עצור מיד וסיים את הדיווח במילה MISSING ואחריה שם השדה
(למשל MISSING:email או MISSING:name). ***

עבור את כל שלבי הווידג'ט בעצמך:
1. בחר {job["party_size"]} סועדים.
2. פתח את בורר התאריך ובחר את התאריך {job["date"]} (גלול בלוח אם צריך).
3. פתח את בורר השעה ובחר {job["time"]} (הרשימה גלילה — גלול עד שתמצא אותה).
4. לחץ על הכפתור "מצאו לי שולחן".
5. בחר אחת השעות הזמינות שמופיעות (הקרובה ביותר למבוקש).
6. במסך הסיכום: סמן את כל תיבות הסימון של התנאים, ולחץ "המשך".
7. מלא פרטי קשר: שם "{job.get("name") or ""}", אימייל "{job.get("email") or ""}", טלפון "{job.get("phone") or ""}".
"""
    # dry_run=True → recon: עוצרים במסך הסיכום *לפני* האישור הסופי (לא סוגרים, גם בלי כרטיס).
    # commit (dry_run=False) → סוגרים באמת, אבל אם נדרש כרטיס אשראי עוצרים שם (PCI).
    if job.get("dry_run", True):
        tail = """8. המשך עד *מסך הסיכום / האישור הסופי* של ההזמנה — המסך שבו רואים את כל פרטי
ההזמנה וכפתור הסיום ("סיום" / "אשר הזמנה" / "הזמן" / "שלם").

*** חוק ברזל: עצור ב*מסך הסיכום*, *לפני* הכפתור הסופי. אל תלחץ לעולם על כפתור
הסיום / "אשר הזמנה" / "הזמן" / "שלם", ואל תזין פרטי כרטיס אשראי — בין אם נדרש
כרטיס ובין אם לא. המטרה היא רק להגיע עד מסך הסיכום, *בלי* לסגור. ***

כשהגעת למסך הסיכום, סיים את הדיווח במילה SUMMARY_REACHED. אם המסך דורש פרטי כרטיס
אשראי כדי לסיים — הוסף אחריה גם את המילה CARD_REQUIRED."""
    else:
        tail = """8. המשך עד מסך האישור הסופי של ההזמנה.

*** חוק ברזל — כרטיס אשראי: אם בשלב כלשהו האתר דורש פרטי כרטיס אשראי / תשלום מראש,
עצור מיד. אל תזין שום פרטי כרטיס ואל תמשיך — מקום שדורש תשלום מראש לא נסגר אוטומטית.
במקרה כזה סיים את הדיווח במילה: CARD_REQUIRED ***

אם לא נדרש כרטיס אשראי: לחץ על כפתור האישור הסופי לסגירת ההזמנה
(למשל "אשר הזמנה" / "סיום" / "הזמן"). ודא שמופיע מסך/הודעת אישור שההזמנה נסגרה.
רק כשההזמנה נסגרה בהצלחה — סיים את הדיווח במילה BOOKED ואחריה מספר האישור אם הופיע.

אם שדה חובה בטופס ריק ואין לך אותו — אל תמלא ואל תמציא; עצור וסיים במילה MISSING
ואחריה שם השדה (למשל MISSING:email)."""
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
