"""
convo_eval — בדיקת שכבת-השיחה עם מודל אמיתי (Tier 2, בתבנית persona_eval).

תרחישים מרובי-תורות משוחזרים משתי השיחות האמיתיות של 23.7 (הבאגים החיים):
תוצאות-דפדפן מוזרקות (mock ל-book_table_bu / recommend_places), מודל השיחה
ומודל הקול-החופשי אמיתיים (Gemini), ושופט אוטומטי — דטרמיניסטי איפה שאפשר
(טוקני שעות/תאריכים) ו-LLM איפה שצריך שיפוט ניסוח.

מה נבדק פר-תרחיש:
  · אין שעות/תאריכים בהודעה שלא באופציות האמיתיות (ולא בעבר) — באגים 1+2
  · אין שליחה כפולה ואין חזרתיות בין הודעות רצופות — באג 3
  · waitlist מנוסח כהצעה, לא "הכל מלא" — באג 4
  · מקום שנפסל לא חוזר בהמלצות — באג 5

הרצה (פקודה אחת, GEMINI_API_KEY מ-.env):
    python poc/convo_eval.py
פלט: עובר/נכשל פר-תרחיש + דוגמאות הכשל; exit code 1 אם משהו נכשל.
"""

import asyncio
import difflib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.config import settings  # noqa: E402

# אפס תלות ברשתות צד-ג' חוץ מ-Gemini: בלי Supabase, בלי Brave, בלי שער גישה.
settings.supabase_url = ""
settings.supabase_service_key = ""
settings.brave_api_key = ""
settings.access_gate = False

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from app import pipeline  # noqa: E402
from app.db import memory  # noqa: E402
from app.models.schemas import ActionResult  # noqa: E402


# פרופיל קיים כמו אצל המשתמשים החיים — בלעדיו כל ready נתקע על שער שם+מייל
# של האונבורדינג במקום להמשיך את התרחיש.
async def _profile(phone):
    return {"phone": phone, "name": "אלון בדיקה", "email": "beta@example.com", "prefs": {}}


memory.get_profile = _profile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX_A = json.load(open(os.path.join(ROOT, "tests/fixtures/convo_a.json"), encoding="utf-8"))[0]
FIX_B = json.load(open(os.path.join(ROOT, "tests/fixtures/convo_b.json"), encoding="utf-8"))[0]
PHONE_A, PHONE_B = FIX_A["phone"], FIX_B["phone"]
OPTIONS_A = FIX_A["prefs"]["_flow"]["await_answer"]["options"]  # 21:30/21:45/22:00 + waitlist
OPTIONS_B_DATES = ["25.07", "26.07", "27.07", "28.07", "29.07"]

_IL = ZoneInfo("Asia/Jerusalem")
TODAY = datetime.now(_IL)
TOMORROW = TODAY + timedelta(days=1)

SENT: list[str] = []


async def _send_text(phone, msg):
    SENT.append(msg)


async def _send_list(phone, body, labels):
    SENT.append(body + "\n" + "\n".join(f"· {lbl}" for lbl in labels))


async def _typing(mid):
    pass


async def _no_pace(s):
    pass


async def _no_release(sid):
    pass


pipeline.send_text = _send_text
pipeline.send_list = _send_list
pipeline.send_typing = _typing
pipeline._pace = _no_pace
pipeline.release_session = _no_release


def _missing_book(field, options):
    async def fake(**kwargs):
        return ActionResult(
            success=False,
            summary=f"MISSING:{field}",
            details={"missing": field, "options": options, "stage": "recon"},
        )

    return fake


def _reset(phone, turns=None):
    SENT.clear()
    for d in (
        pipeline._booking,
        pipeline._await_answer,
        pipeline._resume,
        pipeline._resolved,
        pipeline._pending_pick,
        pipeline._preresolve,
        pipeline._recs,
        pipeline._rejected,
        pipeline._rec_inflight,
        pipeline._turns,
        pipeline._last_out,
        pipeline._pending_commit,
        pipeline._prefetched,
    ):
        d.pop(phone, None)
    if turns:
        now = time.time()
        pipeline._turns[phone] = [{"role": t["role"], "text": t["text"], "ts": now} for t in turns][
            -pipeline.CHAT_TURNS :
        ]
    pipeline._last_seen[phone] = time.time()


async def _drain():
    """מסיים משימות רקע קצרות ומבטל טיימרים ארוכים (נדנוד) שנחמשו בתרחיש."""
    for t in list(pipeline._nudge.values()):
        t.cancel()
    for _ in range(20):
        live = [t for t in pipeline._pending if not t.done()]
        if not live:
            break
        await asyncio.sleep(0.05)


def _allowed(*texts):
    return pipeline._option_tokens(
        [*texts, f"{TODAY.day}.{TODAY.month}", f"{TOMORROW.day}.{TOMORROW.month}", f"{TODAY:%H:%M}"]
    )


def _out():
    return "\n".join(SENT)


# ─── שופט LLM (ניסוח בלבד; העובדות נבדקות דטרמיניסטית) ─────────────────────
_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
JUDGE_MODEL = os.getenv("GEMINI_MODEL", settings.gemini_model)


def judge(question: str, text: str) -> tuple[bool, str]:
    verdict = (
        _client.models.generate_content(
            model=JUDGE_MODEL,
            contents=(
                "אתה בודק איכות של הודעות וואטסאפ מעוזר הזמנות.\n"
                f"השאלה: {question}\n"
                "ענה בשורה אחת: 'PASS' או 'FAIL: <סיבה קצרה>'.\n"
                f"--- ההודעות ---\n{text}"
            ),
            config=types.GenerateContentConfig(temperature=0),
        ).text
        or ""
    ).strip()
    return verdict.upper().startswith("PASS"), verdict


# ─── התרחישים ───────────────────────────────────────────────────────────────


async def scenario_alt_time_waitlist():
    """שיחה A: הנסיך, 22:30 תפוס → MISSING:time עם סלון+מרפסת-waitlist.
    הבאג החי: הכותרת המציאה 20:00...23:30 ו'הכל מלא'."""
    _reset(PHONE_A, FIX_A["prefs"]["_chat"]["turns"][:8])
    pipeline.book_table_bu = _missing_book("time", OPTIONS_A)
    pipeline._resolved[PHONE_A] = {"name": "הנסיך", "url": "http://x", "platform": "ontopo"}
    await pipeline.run_booking(
        PHONE_A,
        {
            "restaurant": "הנסיך",
            "date": f"{TODAY.day:02d}.{TODAY.month:02d}",
            "time": "22:30",
            "party_size": 4,
            "notes": "בחוץ",
        },
    )
    await _drain()
    fails = []
    foreign = pipeline._foreign_option_tokens(_out(), _allowed(*OPTIONS_A, "22:30"))
    if foreign:
        fails.append(f"שעות/תאריכים מומצאים: {foreign}")
    if not re.search(r"רשימת המתנה|רשימת ההמתנה", _out()):
        fails.append("ה-waitlist לא הוצף כאופציה")
    if re.search(r"הכל מלא", _out()):
        fails.append("'הכל מלא' בניסוח למרות אופציות waitlist (הגארד אמור לפסול)")
    ok, verdict = judge(
        "האם ההודעות מציגות את רשימת ההמתנה כאפשרות אמיתית להצטרף אליה "
        "(ולא כ'אין מקום'/'הכל מלא'), ומציעות לסגור רק שעות מהרשימה שנשלחה?",
        _out(),
    )
    if not ok:
        fails.append(f"שופט: {verdict}")
    return fails


async def scenario_alt_date():
    """שיחה B: ג'ניה, אין זמינות בתאריך → MISSING:date עם 25.07-29.07.
    הבאג החי: ההודעה כתבה 24.07-28.07."""
    _reset(PHONE_B, FIX_B["prefs"]["_chat"]["turns"][:10])
    pipeline.book_table_bu = _missing_book("date", OPTIONS_B_DATES)
    pipeline._resolved[PHONE_B] = {"name": "ג'ניה", "url": "http://x", "platform": "ontopo"}
    await pipeline.run_booking(
        PHONE_B,
        {
            "restaurant": "ג'ניה",
            "date": f"{TODAY.day:02d}.{TODAY.month:02d}",
            "time": "22:00",
            "party_size": 3,
            "notes": "בחוץ",
        },
    )
    await _drain()
    fails = []
    foreign = pipeline._foreign_option_tokens(
        _out(), _allowed(*OPTIONS_B_DATES, "22:00", f"{TODAY.day:02d}.{TODAY.month:02d}")
    )
    if foreign:
        fails.append(f"תאריכים/שעות מומצאים: {foreign}")
    return fails


def _missing_state(phone, options, requested_time="22:30"):
    """מצב עצירת MISSING:time חי כפי שנשמר ב-_flow של השיחה האמיתית."""
    pipeline._booking[phone] = {"state": "missing", "info": "time"}
    pipeline._await_answer[phone] = {
        "fields": {
            "restaurant": "הנסיך",
            "date": f"{TODAY.day:02d}.{TODAY.month:02d}",
            "time": requested_time,
            "party_size": 4,
            "task_type": "restaurant",
        },
        "field": "time",
        "options": options,
    }
    # אם המודל בכל זאת יורה ready — הריצה תפגוש שוב את אותו דף (ולא דפדפן אמיתי)
    pipeline.book_table_bu = _missing_book("time", options)
    pipeline._resolved[phone] = {"name": "הנסיך", "url": "http://x", "platform": "ontopo"}


def _turns_until_options(fix):
    """ההיסטוריה עד (וכולל) הודעת האופציות — הרגע שבו הלקוח בחר 23:00 בלייב."""
    turns = fix["prefs"]["_chat"]["turns"]
    for i, t in enumerate(turns):
        if "מרפסת - רשימת המתנה" in (t.get("text") or ""):
            return turns[: i + 1]
    return turns


async def scenario_invalid_pick():
    """שיחה A: הלקוח בחר 23:00 שלא קיים — התשובה חייבת להישאר בתוך האופציות
    האמיתיות ולא לאשר את מה שאין."""
    _reset(PHONE_A, _turns_until_options(FIX_A))
    _missing_state(PHONE_A, OPTIONS_A)
    await pipeline.handle_inbound(PHONE_A, "23:00")
    await _drain()
    fails = []
    foreign = pipeline._foreign_option_tokens(_out(), _allowed(*OPTIONS_A, "22:30", "23:00"))
    if foreign:
        fails.append(f"שעות מומצאות בתשובה: {foreign}")
    if re.search(r"(?<!לא )סגרתי", _out()):
        fails.append("הכריז שסגר על שעה שלא קיימת")
    ok, verdict = judge(
        "הלקוח ביקש שעה שאינה זמינה (23:00). האם ההודעות מבהירות שהיא לא זמינה "
        "ומפנות רק לאפשרויות שקיימות, בלי להמציא שעות אחרות?",
        _out(),
    )
    if not ok:
        fails.append(f"שופט: {verdict}")
    return fails


async def scenario_what_available():
    """פולו-אפ חופשי 'אז מה כן פנוי?' על עצירת MISSING — התשובה רק מהאופציות."""
    _reset(PHONE_A, _turns_until_options(FIX_A))
    _missing_state(PHONE_A, OPTIONS_A)
    await pipeline.handle_inbound(PHONE_A, "אז מה כן פנוי הערב?")
    await _drain()
    fails = []
    foreign = pipeline._foreign_option_tokens(_out(), _allowed(*OPTIONS_A, "22:30"))
    if foreign:
        fails.append(f"שעות מומצאות: {foreign}")
    return fails


async def scenario_no_repeat():
    """שתי הודעות 'מה קורה' רצופות באמצע ריצה — בלי אותה תשובה פעמיים
    (חתימת הבוט מהלייב: 6 הודעות ack רצופות)."""
    _reset(PHONE_A, FIX_A["prefs"]["_chat"]["turns"][:6])
    pipeline._booking[PHONE_A] = {"state": "working", "info": "הנסיך"}
    await pipeline.handle_inbound(PHONE_A, "נו מה קורה עם זה?")
    first = _out()
    SENT.clear()
    await pipeline.handle_inbound(PHONE_A, "מה קורה עם ההזמנה?")
    second = _out()
    await _drain()
    fails = []
    ratio = difflib.SequenceMatcher(None, first, second).ratio()
    if ratio >= 0.95:
        fails.append(f"חזרתיות בין הודעות רצופות (דמיון {ratio:.2f}): {second!r}")
    if re.search(r"(?<!לא )סגרתי", first + second):
        fails.append("הכריז שסגר בזמן שהריצה עוד רצה")
    return fails


async def scenario_rejected_not_recommended():
    """שיחה A: הגזטה כבר נפסלה בשיחה — ההמלצות (עם תוצאות grounding מוזרקות
    שמכילות אותה) חייבות לסנן אותה. הבאג החי: גבר המליץ עליה שוב."""
    _reset(PHONE_A, FIX_A["prefs"]["_chat"]["turns"][:6])
    pipeline._rejected[PHONE_A] = ["הגזטה"]

    async def fake_places(category, area="", constraints="", exclude=None):
        mk = lambda n: {  # noqa: E731
            "name": n,
            "rating": 4.5,
            "reviews": 1200,
            "open_now": True,
            "uri": "",
            "place_id": "",
        }
        return [mk("Gazzetta"), mk("Tirza wine bar"), mk("Wine Dealer"), mk("CÔTE")]

    async def exists(name, area):
        return True

    pipeline.recommend_places = fake_places
    pipeline._rec_exists = exists
    await pipeline.run_recommend(
        PHONE_A,
        {"task_type": "recommend", "category": "wine bar", "city": "Rothschild, Tel Aviv"},
    )
    await _drain()
    fails = []
    if re.search(r"Gazzetta|גזטה", _out()):
        fails.append("המקום שנפסל חזר כהמלצה")
    if "Tirza wine bar" not in _out():
        fails.append("ההמלצות המאומתות לא נשלחו")
    return fails


async def scenario_say_sampling():
    """דגימת הקול החופשי על הצעת-חלופות ×3 — הגארד מחזיק בכל דגימה
    (מודל שהמציא → נפילה שקופה לנוסח הבטוח)."""
    fails = []
    allowed = pipeline._option_tokens(["22:30", *OPTIONS_A])
    for i in range(3):
        msg = await pipeline._say(
            "alt_time_offer",
            {"requested": "22:30", "n_options": len(OPTIONS_A), "_allowed_tokens": allowed},
            fallback=("ה-22:30 תפוס 😮‍💨 אלו השעות שכן פנויות — לסגור אחת?",),
        )
        foreign = pipeline._foreign_option_tokens(msg, _allowed(*OPTIONS_A, "22:30"))
        if foreign:
            fails.append(f"דגימה {i + 1}: טוקנים מומצאים {foreign}: {msg!r}")
    return fails


async def scenario_smalltalk():
    """לייב 24.7 (#9): גבר יצא אגרסיבי בשיחת חולין ("פחות בחפירות", "עזוב אותך
    שטויות") ודחה הודעות קוליות למרות שהמערכת תומכת בהן. הדרישה: צ'יל, זורם
    עם הקטע, מוביל להזמנות בעדינות — ולא דוחה ווקאלים."""
    _reset(PHONE_B)
    await pipeline.handle_inbound(PHONE_B, "מה קורה אחי איזה יום ארוך היה לי היום בעבודה")
    await pipeline.handle_inbound(PHONE_B, "אגב אפשר לשלוח לך הודעות קוליות או שרק בכתב?")
    both = _out()
    await _drain()
    fails = []
    if re.search(r"חפיר|עזוב אותך|פחות זורם|שלח לי בכתב", both):
        fails.append("ניסוח דוחה/אגרסיבי בשיחת חולין")
    ok, verdict = judge(
        "ההודעות הראשונות הן תגובה לשיחת חולין ('יום ארוך בעבודה') והאחרונות לשאלה "
        "אם אפשר לשלוח הודעות קוליות. האם התגובות רגועות וחבריות — זורמות עם שיחת "
        "החולין בלי לדחות אותה ובלי לדחוף באגרסיביות חזרה להזמנות — והאם התשובה "
        "על הקוליות מאשרת שאפשר לשלוח אותן (הוא שומע אותן), בלי לדרוש לעבור לכתב?",
        both,
    )
    if not ok:
        fails.append(f"שופט: {verdict}")
    return fails


SCENARIOS = [
    ("alt_time_waitlist (שיחה A)", scenario_alt_time_waitlist),
    ("alt_date_offer (שיחה B)", scenario_alt_date),
    ("בחירת שעה לא-קיימת 23:00 (שיחה A)", scenario_invalid_pick),
    ("'מה כן פנוי' על עצירת MISSING (שיחה A)", scenario_what_available),
    ("בלי חזרתיות בין הודעות רצופות", scenario_no_repeat),
    ("מקום שנפסל לא חוזר בהמלצות (שיחה A)", scenario_rejected_not_recommended),
    ("דגימת קול-חופשי — הצעת חלופות", scenario_say_sampling),
    ("שיחת חולין רגועה + הודעות קוליות", scenario_smalltalk),
]


def main() -> None:
    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("חסר GEMINI_API_KEY ב-.env")
    print(f"מודל שיחה/קול: {settings.gemini_model} · שופט: {JUDGE_MODEL}\n")
    passed = 0
    for name, fn in SCENARIOS:
        try:
            fails = asyncio.run(fn())
        except Exception as e:  # noqa: BLE001 — תרחיש שקרס = כשל, לא הפלת הריצה
            fails = [f"חריגה בתרחיש: {e!r}"]
        ok = not fails
        passed += ok
        print(f"{'✅' if ok else '❌'}  [{name}]")
        for f in fails:
            print(f"    · {f}")
        if not ok and SENT:
            print("    -- ההודעות שנשלחו --")
            for m in SENT:
                print("    | " + m.replace("\n", "\n    | "))
    print(f"\n— עבר {passed}/{len(SCENARIOS)} —")
    if passed < len(SCENARIOS):
        sys.exit(1)


if __name__ == "__main__":
    main()
