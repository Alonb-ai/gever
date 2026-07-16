"""book_table_bu — שכבת הניווט החדשה: מריץ את bu_runner (browser-use) ב-subprocess
ומחזיר ActionResult, בדיוק כמו ה-book_table הישן — כך שה-pipeline כמעט לא משתנה.

למה subprocess: browser-use מצמיד google-genai==1.65 ↔ ה-app על 2.8 (לא יכולים לחיות
באותו venv). אז ה-agent רץ ב-.venv-bu נפרד, מאחורי גבול דק של JSON-in/JSON-out.
"""

import asyncio
import json
import logging
import os
import time as _time
import uuid

import httpx

from app.config import settings
from app.models.schemas import ActionResult

log = logging.getLogger("gever")

_RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bu_runner.py")
BU_TIMEOUT_S = 600  # ponytail: תקרה קשיחה (10 דק') — browser-use עובר את כל זרימת Ontopo
# עד הסיכום; 5 דק' קטעו ריצות חיות באמצע (dry-run #2). agent תקוע נכשל בקול, לא בדממה.


async def _run_subprocess(job: dict) -> None:
    """מריץ את bu_runner ב-.venv-bu ומזרים את ה-job ב-stdin. מופרד כדי שיהיה ניתן ל-mock.
    מעבירים את מפתח ה-Gemini ב-env: pydantic-settings קורא .env לאובייקט, *לא* ל-os.environ,
    אז ה-subprocess לא יראה אותו אחרת."""
    env = {**os.environ}
    if settings.gemini_api_key:
        env["GEMINI_API_KEY"] = settings.gemini_api_key
        env["GOOGLE_API_KEY"] = settings.gemini_api_key
    # מפתחות ספקי-נווט חלופיים (השוואת מודלים: MODEL_NAME בקידומת claude-/gpt-/bu-) —
    # עוברים רק אם מולאו; בשוטף ריקים וה-env לא משתנה.
    for env_var, value in (
        ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
        ("OPENAI_API_KEY", settings.openai_api_key),
        ("BROWSER_USE_API_KEY", settings.browser_use_api_key),
    ):
        if value:
            env[env_var] = value
    # ה-reasoning של ה-agent (browser-use מדפיס כל צעד: הערכה, זיכרון, מטרה הבאה)
    # נכתב לקובץ במקום להיזרק — ניתן לקריאה live (tail) וגם אחרי timeout/kill.
    with open(job["steps_path"], "wb") as steps:
        proc = await asyncio.create_subprocess_exec(
            settings.bu_venv_path,
            _RUNNER,
            stdin=asyncio.subprocess.PIPE,
            stdout=steps,
            stderr=steps,
            env=env,
        )
        try:
            await asyncio.wait_for(proc.communicate(json.dumps(job).encode()), timeout=BU_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()  # ponytail: הורג את ה-runner; browser-use סוגר את Chrome ביציאה
            await proc.wait()
            raise


def _steps_tail(path: str, n: int = 2500) -> str:
    """הזנב של יומן הצעדים — התשובה ל'למה הוא נתקע/בחר ככה' בלי לפתוח את השרת."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    except OSError:
        return "(אין יומן צעדים)"


_BB_API = "https://api.browserbase.com/v1"


async def _bb(method: str, path: str, body: dict | None = None) -> dict:
    """קריאת Browserbase API אחת. docs.browserbase.com/reference/api."""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.request(
            method,
            f"{_BB_API}{path}",
            json=body,
            headers={
                "X-BB-API-Key": settings.browserbase_api_key,
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _bb_create_session() -> tuple[str, str]:
    """סשן Browserbase חדש → (session_id, connectUrl). keepAlive: הסשן שורד ניתוק
    CDP כדי לאפשר pause-resume (עצירה על שאלה ללקוח → המשך מאותו מסך). timeout=1800
    הוא תקרת העלות לסשן נטוש — שחרור מפורש (release_session) בכל סוף ריצה."""
    data = await _bb(
        "POST",
        "/sessions",
        {
            "projectId": settings.browserbase_project_id,
            "proxies": True,
            "keepAlive": True,
            "timeout": 1800,
        },
    )
    return data["id"], data["connectUrl"]


async def _bb_live_connect_url(session_id: str) -> str | None:
    """connectUrl של סשן אם הוא עדיין רץ, אחרת None (פג/נסגר/שגיאה) — לצורך resume."""
    try:
        data = await _bb("GET", f"/sessions/{session_id}")
        return data.get("connectUrl") if data.get("status") == "RUNNING" else None
    except Exception as exc:  # noqa: BLE001 — סשן מת = פשוט ריצה טרייה
        log.warning("bb session check failed (%s): %s", session_id, exc)
        return None


async def sweep_orphan_sessions() -> int:
    """שחרור סשני keepAlive יתומים — ריצה שמתה (redeploy/קריסה) משאירה סשן חי שמחויב
    עד ה-timeout (30 דק'). רץ בעליית השרת: בנקודה הזאת אין לנו שום ריצה חיה (ה-state
    בזיכרון התהליך), אז כל סשן RUNNING בפרויקט הוא יתום. מחזיר כמה שוחררו."""
    data = await _bb("GET", f"/sessions?projectId={settings.browserbase_project_id}&status=RUNNING")
    sessions = data if isinstance(data, list) else []
    for s in sessions:
        await release_session(s.get("id"))
    return len(sessions)


async def live_view_url(session_id: str | None) -> str | None:
    """לינק Live View אינטראקטיבי לסשן חי (debuggerFullscreenUrl) — הלקוח פותח אותו
    ורואה את הדפדפן בדיוק בנקודת העצירה, עם כל מה שכבר מולא, ומשלים את הכרטיס בעצמו
    (אנחנו לא נוגעים בכרטיס — PCI). None אם אין סשן/כשל → הקורא נופל ללינק דף רגיל."""
    if not session_id:
        return None
    try:
        data = await _bb("GET", f"/sessions/{session_id}/debug")
        return data.get("debuggerFullscreenUrl") or None
    except Exception as exc:  # noqa: BLE001 — אין live view זה downgrade, לא כשל
        log.warning("bb live view failed (%s): %s", session_id, exc)
        return None


async def release_session(session_id: str | None) -> None:
    """שחרור סשן keepAlive — בלעדיו דקות-דפדפן נצברות באידל עד ה-timeout. best-effort."""
    if not session_id:
        return
    try:
        await _bb(
            "POST",
            f"/sessions/{session_id}",
            {"projectId": settings.browserbase_project_id, "status": "REQUEST_RELEASE"},
        )
    except Exception as exc:  # noqa: BLE001 — ה-timeout של הסשן הוא רשת הביטחון
        log.warning("bb session release failed (%s): %s", session_id, exc)


async def book_table_bu(
    *,
    restaurant: str,
    page_url: str,
    platform: str = "",  # רמיזה ל-agent (ontopo/tabit) — לא חובה, ה-task אגנוסטי
    date: str,
    time: str,  # noqa: A002 — תואם לחתימת book_table הישנה
    party_size: int,
    name: str = "",
    email: str = "",
    phone: str = "",
    notes: str = "",  # העדפות ביצוע מהלקוח (אזור ישיבה וכו') — מוזרק ל-task
    dry_run: bool = True,
    resume: dict | None = None,  # {"session_id","recap"} — המשך סשן חי מאותו מסך (pause-resume)
    keep_on_summary: bool = False,  # השאר סשן חי גם על SUMMARY_REACHED — לסגירה-באותו-סשן
    time_flex: bool = False,  # הלקוח גמיש בשעה → מותר לסגור ±60 דק' בלי לעצור ולשאול
) -> ActionResult:
    """מזמין (Ontopo/Tabit) דרך browser-use agent אוטונומי. עוצר בשלב הכרטיס (שער בטיחות).

    pause-resume: ריצה שנעצרה על MISSING משאירה את סשן ה-Browserbase חי (keepAlive),
    ו-details.session_id חוזר כדי שה-pipeline ישמור אותו. כשהלקוח עונה — resume עם
    אותו session_id ממשיך מאותו מסך (שניות במקום ניווט מחדש). סשן מת → ריצה טרייה."""
    # uuid ולא רק timestamp: שתי הזמנות מקבילות באותה ms דרסו זו את תוצאת זו ב-/tmp
    run_id = f"{int(_time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
    # record_dir ריק = בלי הקלטה בכלל (פרודקשן). הבאג הישן: fallback ל-/tmp הדליק
    # וידאו+GIF בטעות — יצירת GIF מריצה של דקות תקעה את ה-runner הרבה אחרי שהדפדפן
    # סיים (שרת 2 ליבות), והלקוח לא קיבל תשובה. קובץ התוצאה תמיד נכתב (גם בלי הקלטה).
    record_dir = os.path.join(settings.bu_record_dir, run_id) if settings.bu_record_dir else ""
    result_dir = record_dir or "/tmp"
    result_path = os.path.join(result_dir, f"result_{run_id}.json")
    steps_path = os.path.join(result_dir, f"steps_{run_id}.log")
    job = {
        "url": page_url,
        "platform": platform,
        "date": date,
        "time": time,
        "party_size": party_size,
        "name": name,
        "email": email,
        "phone": phone,
        "notes": notes,
        "dry_run": dry_run,
        "time_flex": time_flex,
        "model": settings.model_name.split("/")[-1],
        "headless": settings.bu_headless,
        "record_dir": record_dir,
        "result_path": result_path,
        "steps_path": steps_path,
        "max_steps": 40,
    }
    session_id: str | None = None
    if settings.bu_browser == "browserbase":
        cdp = None
        if resume and resume.get("session_id"):
            cdp = await _bb_live_connect_url(resume["session_id"])
            if cdp:
                session_id = resume["session_id"]
                job["resume"] = {"recap": (resume.get("recap") or "")[:400]}
            # סשן מת → נופלים בשקט לריצה טרייה (התשובה כבר ב-notes) — אין הבדל ללקוח
        if not cdp:
            session_id, cdp = await _bb_create_session()
        job["cdp_url"] = cdp
    elif settings.bu_chrome_path:
        job["chrome_path"] = settings.bu_chrome_path

    try:
        os.makedirs(result_dir, exist_ok=True)
        await _run_subprocess(job)
        with open(result_path, encoding="utf-8") as f:
            r = json.load(f)
        log.info("bu steps tail (%s):\n%s", steps_path, _steps_tail(steps_path))
    except asyncio.TimeoutError:
        await release_session(session_id)
        # הזנב עונה על "למה נתקע?" — הצעדים האחרונים של ה-agent לפני ה-kill
        log.warning("bu TIMEOUT steps tail (%s):\n%s", steps_path, _steps_tail(steps_path))
        return ActionResult(
            success=False,
            summary="אחי זה נתקע לי, לקח יותר מדי. ננסה שוב?",
            details={"stage": "timeout", "steps_tail": _steps_tail(steps_path, 1500)},
        )
    except Exception as e:  # noqa: BLE001 — כשל הופך להודעה כנה, לא ל-traceback
        await release_session(session_id)
        log.warning("bu ERROR steps tail (%s):\n%s", steps_path, _steps_tail(steps_path))
        return ActionResult(
            success=False,
            summary="נתקעתי באמצע, לא הצלחתי לסגור. ננסה שוב?",
            details={"stage": "error", "error": str(e)},
        )

    # הסשן נשאר חי בעצירות שמחכות ללקוח: שדה חסר (pause-resume), קיר-כרטיס
    # (הלקוח מקבל Live View וממשיך בעצמו מאותו מסך — Ontopo הוא SPA, לינק רגיל
    # מאבד את כל מה שמולא), ומסך סיכום כשהקורא ביקש keep_on_summary — אז "מאשר"
    # של הלקוח נסגר בקליק באותו סשן במקום ניווט מלא מחדש (חוסך דקות מהלופ).
    # כל תוצאה אחרת — משחררים מיד, keepAlive מחויב גם באידל. סשן ממתין נטוש
    # נסגר לבד ב-timeout של הסשן (1800s) או ב-sweeper בעלייה.
    waiting = (
        bool(
            r.get("missing")
            or r.get("card_required")
            or (keep_on_summary and r.get("summary_reached"))
        )
        and session_id is not None
    )
    if not waiting:
        await release_session(session_id)

    return ActionResult(
        success=bool(r.get("success")),
        summary=r.get("message") or "",
        details={
            "stage": r.get("stage"),
            "card_required": r.get("card_required"),
            "booked": r.get("booked"),
            "confirmation": r.get("confirmation"),
            "summary_reached": r.get("summary_reached"),
            "missing": r.get("missing"),
            "options": r.get("options") or [],
            "page_now": r.get("page_now") or "",
            "failed": r.get("failed"),
            "time": r.get("time"),
            "perk": r.get("perk"),
            "agreed": r.get("agreed") or [],
            "restaurant": restaurant,
            "record_dir": record_dir,
            "session_id": session_id if waiting else None,
            # זנב יומן-הצעדים חוזר עם התוצאה — נשמר ב-_flow ושורד redeploy
            # (נלמד 15.7: הזנב שנכתב רק ללוג הקונטיינר מת יחד איתו בכל deploy).
            "steps_tail": _steps_tail(steps_path, 1500),
        },
    )
