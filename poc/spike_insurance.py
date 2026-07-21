"""spike ביטוח: הזרימה מקצה לקצה מהמאק — resolve קבוע (פספורטכארד) → browser-use
על Browserbase ב-DRY_RUN → הדפסת ActionResult + נתיב יומן הצעדים.

חוקי ברזל של האבטיפוס:
- DRY_RUN תמיד (מקודד קשיח כאן, לא פרמטר, עם נעילה שמסרבת לכל עקיפה) — לעולם לא
  ממלאים פרטי תשלום ולא סוגרים פוליסה. עצירה כנה ב-CARD_REQUIRED / MISSING מרובה /
  FAILED (כולל blocked — האתר מחזיר 403 ל-fetch רגיל, ייתכן WAF גם מול Browserbase)
  היא הצלחה של האבטיפוס.
- נתוני דמה בלבד — אף פרט אמיתי של לקוח לא נכנס לספייק.
- session חי שחזר (קיר-כרטיס/MISSING משאירים keepAlive) — משוחרר תמיד ב-finally.
- לולאת עומק (סבב 2): עצירת MISSING נענית מנתוני-הבדיקה שהספייק מגדיר (_test_answer)
  ו-resume ממשיך מאותו מסך — בדיוק מסלול ה-pipeline. שאלה רפואית או מפתח בלי
  תשובת-בדיקה ⇒ עצירה כנה; על שאלות בריאות הספייק לעולם לא עונה (הצהרה משפטית).

הרצה (מתוך שורש ה-worktree, בשביל ה-.env):
    .venv/bin/python poc/spike_insurance.py ["יעד"] [DD.MM יציאה] [DD.MM חזרה] [מבטח]
ברירות מחדל: "יוון", מחר, מחר+14, פספורטכארד. מבטח = מפתח מ-INSURANCE_COMPANIES
(passportcard/harel/phoenix/aig/migdal) — recon לקבוצה הסגורה של ורטיקל הביטוח.
הנוסעים: שני בגירים עם תאריכי לידה דמה.
היעד = *מדינה* (לקח ריצה חיה 1: דף היעד הוא חיפוש מדינות, "אירופה" לא מחזיר כלום).
"""

import asyncio
import glob
import json
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.automation.browser_book import book_table_bu, release_session  # noqa: E402
from app.automation.resolve import INSURANCE_COMPANIES, resolve_insurance_url  # noqa: E402
from app.config import settings  # noqa: E402

DRY_RUN = True  # חוק ברזל: הספייק מסרב לרוץ אחרת (assert למטה) — אין כאן פרמטר

_TOMORROW = date.today() + timedelta(days=1)
_RETURN = date.today() + timedelta(days=15)


def _arg(i: int, default: str) -> str:
    return sys.argv[i] if len(sys.argv) > i and sys.argv[i] else default


# --- נתוני הבדיקה של לולאת העומק (דמה בלבד — מותרים לפי חוקי הברזל של הספייק) ---
# לקח ריצה חיה 3.1: ערכי-בדיקה קנוניים (ת"ז 123456782/111111118, טלפון 0501234567,
# example.com, "ישראלי") מדליקים אצל פספורטכארד soft-block "בהתאם לנתונים שהזנת לא
# ניתן להתקדם ברכישה באתר" (FAILED:phone_only) אחרי ההצהרה הרפואית — נתוני הדמה
# חייבים להיראות סבירים: ת"ז אקראית עם ספרת ביקורת תקינה, דומיין מייל אמיתי.
_P2 = re.compile(r"p2|passenger_?2|traveler_?2|second")
# שאלות רפואיות = הצהרה משפטית: הספייק לעולם לא עונה עליהן, גם לא מנתוני בדיקה.
_HEALTH = re.compile(
    r"health|medical|declaration|disease|illness|chronic|medication|"
    r"treatment|pregnan|smok|surgery|hospital|diagnos"
)
# בחירה כפויה שמותר לספייק להכריע בה (אופציה ראשונה מהדף) — רק מפתחות לוגיסטיים.
_SAFE_CHOICE = re.compile(r"pickup|destination|region|delivery|terminal")
# פרטי כרטיס אשראי/תשלום = קיר התשלום (CARD_REQUIRED) — לא שדה-חסר. הספייק לעולם לא
# מזין פרטי כרטיס, גם לא נתוני-דמה (לקח recon AIG 19.7: הטופס גובה שם/ת"ז בעל-כרטיס
# במסך הסיכום; ה-agent המתוקן מדווח CARD_REQUIRED, וגם אם דיווח MISSING — עוצרים בכנות).
_CARD = re.compile(r"card|cvv|cvc|expiry|expiration|credit")


def _test_answer(key: str, options_by_field: dict) -> str | None:
    """ערך-בדיקה מוגדר-ספייק למפתח ש-agent דיווח כ-MISSING. None = אין — עוצרים בכנות."""
    if _HEALTH.search(key) or _CARD.search(key):
        return None
    p2 = bool(_P2.search(key))
    if key == "id" or "id_number" in key or key.endswith("_id"):
        return "376435996" if p2 else "389784208"  # ת"ז דמה אקראית עם ספרת ביקורת תקינה
    if "gender" in key or "sex" in key:
        return "נקבה" if p2 else "זכר"
    if "birth" in key:
        return "20.11.1992" if p2 else "15.05.1990"
    if "first_name" in key:
        return ("Dana" if p2 else "Alon") if "english" in key else ("דנה" if p2 else "אלון")
    if "last_name" in key or "family" in key:
        return "Levi" if "english" in key else "לוי"
    if "email" in key:
        return "alonlevi1990@gmail.com"
    if "phone" in key or "mobile" in key:
        return "0523894716"
    # כתובת בעל-הפוליסה — טפסי מבטחים (הפניקס/מגדל) גובים כתובת מגורים לפני הפרמיה;
    # בלי נתוני-דמה כאן ה-recon נעצר באמצע. ערכי דמה סבירים בלבד (חוקי הברזל).
    if "street" in key:
        return "הרצל"
    if "house" in key:  # house_number / house_no — מספר בית
        return "10"
    if "apartment" in key or key.endswith("apt") or "_apt" in key:
        return "5"
    if "zip" in key or "postal" in key:
        return "6100000"
    if "city" in key or "settlement" in key:
        return "תל אביב"
    opts = options_by_field.get(key) or []
    if opts and _SAFE_CHOICE.search(key):
        return opts[0]
    return None


def _print_result(res, phase: str) -> None:
    print(f"\n================ SPIKE RESULT — {phase} ================")
    print("success:", res.success)
    print("summary:", res.summary)
    print("details:", json.dumps(res.details, ensure_ascii=False, indent=2))
    # נתיב יומן הצעדים (steps_<run_id>.log) — נכתב ל-record_dir, או /tmp בלי הקלטה.
    result_dir = (res.details or {}).get("record_dir") or "/tmp"
    logs = sorted(glob.glob(os.path.join(result_dir, "steps_*.log")), key=os.path.getmtime)
    print("steps log:", logs[-1] if logs else "(לא נמצא)")


async def main() -> None:
    assert DRY_RUN is True, "הספייק רץ רק ב-DRY_RUN — אין מסלול commit באבטיפוס"
    destination = _arg(1, "יוון")
    depart = _arg(2, f"{_TOMORROW.day:02d}.{_TOMORROW.month:02d}")
    ret = _arg(3, f"{_RETURN.day:02d}.{_RETURN.month:02d}")
    company = _arg(4, "")  # ריק = ברירת המחדל (פספורטכארד) — ההתנהגות הקיימת בדיוק
    assert not company or company in INSURANCE_COMPANIES, (
        f"מבטח לא מוכר: {company!r} — הקבוצה הסגורה: {sorted(INSURANCE_COMPANIES)}"
    )

    if settings.bu_browser != "browserbase":
        print(f"אזהרה: BU_BROWSER={settings.bu_browser!r} (לא browserbase) — רץ לפי ה-.env")

    found = await resolve_insurance_url(company or None)
    print("resolve:", json.dumps(found, ensure_ascii=False, indent=2), flush=True)

    print(
        f"quote (DRY_RUN): {destination}, {depart} → {ret}, 2 נוסעים → {found['url']}",
        flush=True,
    )
    res = None
    base_kwargs = dict(
        restaurant=f"ביטוח נסיעות ל{destination}",
        page_url=found["url"],
        platform=found.get("platform") or "",
        date=depart,
        time="",
        party_size=2,
        # נתוני דמה מלאים — כדי להגיע רחוק ככל האפשר לפני עצירת MISSING כנה.
        name="אלון לוי",
        email="alonlevi1990@gmail.com",
        phone="0523894716",
        dry_run=DRY_RUN,  # חוק ברזל: לעולם לא False באבטיפוס
        task_type="insurance",
        insurance={
            "destination": destination,
            "return_date": ret,
            "travelers": ["15.05.1990", "20.11.1992"],
            "health": "אין",
            "addons": "",
        },
    )
    try:
        res = await book_table_bu(**base_kwargs)
        _print_result(res, "ריצה ראשונה")

        # לולאת העומק: MISSING ⇒ תשובות-בדיקה + resume מאותו מסך (מסלול ה-pipeline).
        # טופס רב-דפי ⇒ מותרות כמה עצירות, אחת לדף — עד 3 סבבי resume.
        for round_i in range(1, 4):
            d = res.details or {}
            fields = d.get("missing_fields") or []
            sid = d.get("session_id")
            if res.success or not fields or not sid:
                break
            answers: dict = {}
            unanswerable: list = []
            for k in fields:
                v = _test_answer(k, d.get("options_by_field") or {})
                if v is None:
                    unanswerable.append(k)
                else:
                    answers[k] = v
            if unanswerable:
                print(
                    f"\nעצירה כנה (סבב {round_i}): אין תשובת-בדיקה ל-{unanswerable} — "
                    "לא ממציאים (שאלות בריאות לעולם לא נענות מהספייק).",
                    flush=True,
                )
                break
            print(f"\nresume {round_i}: משלים {len(answers)} שדות מנתוני הבדיקה:", flush=True)
            print(json.dumps(answers, ensure_ascii=False, indent=2), flush=True)
            res = await book_table_bu(
                **base_kwargs,
                form_answers=answers,
                resume={"session_id": sid, "recap": (d.get("stage") or "")[:400]},
            )
            _print_result(res, f"resume {round_i}")
    finally:
        # חוק ברזל: סשן חי שחזר משוחרר תמיד — גם אם ההדפסות למעלה נפלו.
        session_id = ((res.details or {}) if res else {}).get("session_id")
        if session_id:
            await release_session(session_id)
            print("released browserbase session:", session_id)


if __name__ == "__main__":
    asyncio.run(main())
