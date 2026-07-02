"""book_table_bu — שכבת הניווט החדשה: מריץ את bu_runner (browser-use) ב-subprocess
ומחזיר ActionResult, בדיוק כמו ה-book_table הישן — כך שה-pipeline כמעט לא משתנה.

למה subprocess: browser-use מצמיד google-genai==1.65 ↔ ה-app על 2.8 (לא יכולים לחיות
באותו venv). אז ה-agent רץ ב-.venv-bu נפרד, מאחורי גבול דק של JSON-in/JSON-out.
"""

import asyncio
import json
import os
import time as _time

import httpx

from app.config import settings
from app.models.schemas import ActionResult

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
    proc = await asyncio.create_subprocess_exec(
        settings.bu_venv_path,
        _RUNNER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        await asyncio.wait_for(proc.communicate(json.dumps(job).encode()), timeout=BU_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()  # ponytail: הורג את ה-runner; browser-use סוגר את Chrome ביציאה
        await proc.wait()
        raise


async def _cdp_url() -> str:
    """יוצר סשן Browserbase ומחזיר את ה-connectUrl (CDP-over-WS) ל-browser-use.
    Browserbase מטפל ב-stealth/CAPTCHA/proxy — solveCaptchas דלוק כברירת-מחדל בצד שלהם.
    docs: https://docs.browserbase.com/reference/api/create-a-session"""
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            "https://api.browserbase.com/v1/sessions",
            headers={
                "X-BB-API-Key": settings.browserbase_api_key,
                "Content-Type": "application/json",
            },
            json={"projectId": settings.browserbase_project_id, "proxies": True},
        )
        resp.raise_for_status()
        return resp.json()["connectUrl"]


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
    dry_run: bool = True,
) -> ActionResult:
    """מזמין (Ontopo/Tabit) דרך browser-use agent אוטונומי. עוצר בשלב הכרטיס (שער בטיחות)."""
    run_id = str(int(_time.time() * 1000))
    record_dir = os.path.join(settings.bu_record_dir, run_id) if settings.bu_record_dir else "/tmp"
    result_path = os.path.join(record_dir, f"result_{run_id}.json")
    job = {
        "url": page_url,
        "platform": platform,
        "date": date,
        "time": time,
        "party_size": party_size,
        "name": name,
        "email": email,
        "phone": phone,
        "dry_run": dry_run,
        "model": settings.model_name.split("/")[-1],
        "headless": settings.bu_headless,
        "record_dir": record_dir,
        "result_path": result_path,
        "max_steps": 40,
    }
    if settings.bu_browser == "browserbase":
        job["cdp_url"] = await _cdp_url()
    elif settings.bu_chrome_path:
        job["chrome_path"] = settings.bu_chrome_path

    try:
        os.makedirs(record_dir, exist_ok=True)
        await _run_subprocess(job)
        with open(result_path, encoding="utf-8") as f:
            r = json.load(f)
    except asyncio.TimeoutError:
        return ActionResult(
            success=False,
            summary="אחי זה נתקע לי, לקח יותר מדי. ננסה שוב?",
            details={"stage": "timeout"},
        )
    except Exception as e:  # noqa: BLE001 — כשל הופך להודעה כנה, לא ל-traceback
        return ActionResult(
            success=False,
            summary="נתקעתי באמצע, לא הצלחתי לסגור. ננסה שוב?",
            details={"stage": "error", "error": str(e)},
        )

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
            "restaurant": restaurant,
            "record_dir": record_dir,
        },
    )
