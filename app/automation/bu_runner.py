"""bu_runner — נוהג הזמנת מסעדה ב-Ontopo דרך browser-use agent (ניווט אוטונומי).

רץ ב-.venv-bu בלבד (browser-use מצמיד google-genai==1.65, מתנגש עם ה-app שעל 2.8),
ולכן הקובץ הזה מייבא *רק* browser_use + stdlib — לעולם לא app.*. מופעל כ-subprocess:
    .venv-bu/bin/python app/automation/bu_runner.py   < job.json

קלט: JSON job ב-stdin. פלט: כותב JSON תוצאה ל-job["result_path"] (נקי, בלי ערבוב עם
ה-logs הרועשים של browser-use ב-stdout/stderr).

חוק ברזל (שער בטיחות): המשימה עוצרת *לפני* הזנת כרטיס אשראי / אישור סופי. גם dry_run
וגם לא — בינתיים תמיד עוצרים בשלב הכרטיס (סגירה אמיתית עם כרטיס = עבודה עתידית).
"""

import asyncio
import json
import os
import sys


def _build_task(job: dict) -> str:
    return f"""
לך לכתובת {job["url"]} (אתר הזמנות מסעדה Ontopo, בעברית).
המטרה: להזמין שולחן ל-{job["party_size"]} אנשים בתאריך {job["date"]} בשעה {job["time"]}.

עבור את כל שלבי הווידג'ט בעצמך:
1. בחר {job["party_size"]} סועדים.
2. פתח את בורר התאריך ובחר את התאריך {job["date"]} (גלול בלוח אם צריך).
3. פתח את בורר השעה ובחר {job["time"]} (הרשימה גלילה — גלול עד שתמצא אותה).
4. לחץ על הכפתור "מצאו לי שולחן".
5. בחר אחת השעות הזמינות שמופיעות (הקרובה ביותר למבוקש).
6. במסך הסיכום: סמן את כל תיבות הסימון של התנאים, ולחץ "המשך".
7. מלא פרטי קשר: שם "{job.get("name") or "אלון"}", אימייל "{job.get("email") or ""}", טלפון "{job.get("phone") or ""}".
8. המשך עד שאתה מגיע לשלב של פרטי כרטיס אשראי / תשלום.

*** חוק ברזל: עצור בשלב כרטיס האשראי. אל תזין שום פרטי כרטיס אשראי, ואל תלחץ על
האישור הסופי / "שלם" / "אשר הזמנה". המטרה היא רק להגיע עד שם. ***

בסיום דווח: לאיזה שלב הגעת, והאם נדרש כרטיס אשראי כדי לסיים.
"""


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
    low = final.lower()
    card = ("אשראי" in final) or ("card" in low) or ("כרטיס" in final)
    return {"success": bool(final), "stage": final[:400], "card_required": card, "message": final}


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
