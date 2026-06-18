"""
מנוע צעד-דפדפן חסין: עושה פעולה, *מאמת* שהיא נתפסה, ומרפא את עצמו ב-retry.

הבעיה שזה פותר: Stagehand act() על ווידג'ט מותאם לפעמים מחזיר success בלי שהמצב
באמת השתנה (כשל שקט, לסירוגין). הפתרון: אחרי כל פעולה — extract של המצב ובדיקה
שהוא תואם לכוונה; אם לא, retry בהסלמה (blind act → observe→act דטרמיניסטי). אם כל
הסולם נכשל — מחזירים כישלון כן עם trace, לא תקיעה ולא הנחה.

אגנוסטי לאתר: הפלייבוק (ontopo/קולנוע/ביטוח) מספק לכל צעד את (action, מה לקרוא,
ומה נחשב הצלחה). כאן רק המכניקה.
"""

import asyncio
import logging
from typing import Any, Callable

log = logging.getLogger("gever")

SETTLE_S = 1.2  # ponytail: השהיה קבועה אחרי פעולה כדי שה-UI יתייצב לפני קריאה.
# שדרוג: wait-for-network-idle אם יתברר כלא מספיק.


async def settle(secs: float = SETTLE_S) -> None:
    await asyncio.sleep(secs)


async def extract(session, instruction: str, schema: dict) -> dict:
    """extract → dict שטוח (data.result). {} בכשל, לא מפיל."""
    try:
        r = await session.extract(instruction=instruction, schema=schema)
        return (r.model_dump().get("data") or {}).get("result") or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("extract failed (%s): %s", instruction, exc)
        return {}


async def observe_first(session, instruction: str) -> dict | None:
    """המועמד הראשון מ-observe, או None אם האלמנט לא קיים/כשל. None = 'לא נמצא'
    הוא אות אמיתי (למשל תא-לוח שעדיין לא נפתח)."""
    try:
        o = await session.observe(instruction=instruction)
        cands = (o.model_dump().get("data") or {}).get("result") or []
        return cands[0] if cands else None
    except Exception as exc:  # noqa: BLE001
        log.warning("observe failed (%s): %s", instruction, exc)
        return None


def _clean_candidate(c: dict) -> dict:
    """מנקה מועמד observe ל-ActionParam תקין ל-act(): רק description+selector
    (חובה) + method/arguments אם יש. משמיטים backend_node_id=None ששובר validation."""
    out = {"description": c.get("description") or "", "selector": c.get("selector") or ""}
    if c.get("method"):
        out["method"] = c["method"]
    if c.get("arguments"):
        out["arguments"] = c["arguments"]
    return out


async def _attempt(session, action: str, observe_for: str | None, escalate: bool) -> str:
    """ניסיון פעולה אחד. escalate=False → blind act. escalate=True → observe→act
    דטרמיניסטי (עם fallback להוראה ממוקדת אם ה-candidate נדחה). מחזיר את ה'how'."""
    if escalate and observe_for:
        cand = await observe_first(session, observe_for)
        if cand:
            try:
                await session.act(input=_clean_candidate(cand))
                return "observe-act"
            except Exception as exc:  # noqa: BLE001 — candidate נדחה → הוראה ממוקדת
                log.warning("act(candidate) rejected, targeted instruction: %s", exc)
                await session.act(input=f"{action} — לחץ על: {cand.get('description', '')}")
                return "targeted"
    await session.act(input=action)
    return "blind"


async def act_verified(
    session,
    *,
    action: str,
    read_instruction: str,
    read_schema: dict,
    ok: Callable[[dict], Any],
    observe_for: str | None = None,
    tries: int = 3,
    trace: list | None = None,
) -> tuple[bool, dict]:
    """
    מבצע `action` ומאמת שוב ושוב שה-state שנקרא מקיים ok(state). מסלים מ-blind act
    ל-observe→act. מחזיר (success, last_state). מוסיף רשומות ל-trace אם ניתן.

    ok מקבל את ה-state שחולץ ומחזיר truthy אם הצעד הצליח (הפלייבוק מגדיר 'הצליח').
    """
    state: dict = {}
    for attempt in range(1, tries + 1):
        try:
            how = await _attempt(session, action, observe_for, escalate=attempt >= 2)
        except Exception as exc:  # noqa: BLE001 — פעולה זרקה → רושמים וממשיכים לניסיון הבא
            log.warning("act '%s' attempt %d raised: %s", action, attempt, exc)
            how = f"error:{exc}"
            if trace is not None:
                trace.append({"action": action, "attempt": attempt, "how": how, "ok": False})
            await settle()
            continue
        await settle()
        state = await extract(session, read_instruction, read_schema)
        good = bool(ok(state))
        if trace is not None:
            trace.append(
                {"action": action, "attempt": attempt, "how": how, "ok": good, "state": state}
            )
        if good:
            return True, state
    return False, state


def demo() -> None:
    """self-check עם session מזויף: מוודא שהסולם מסלים, עוצר על הצלחה, ונכשל בכבוד."""

    class FakeSession:
        """מצליח רק בניסיון `succeed_on` (0=אף פעם). סופר act/observe."""

        def __init__(self, succeed_on: int):
            self.succeed_on = succeed_on
            self.acts = 0
            self.observes = 0

        async def act(self, *, input):  # noqa: A002
            self.acts += 1

        async def observe(self, *, instruction):
            self.observes += 1
            return _Resp(
                {"data": {"result": [{"description": "d", "selector": "s", "method": "click"}]}}
            )

        async def extract(self, *, instruction, schema):
            ok = self.acts >= self.succeed_on if self.succeed_on else False
            return _Resp({"data": {"result": {"val": "yes" if ok else "no"}}})

    class _Resp:
        def __init__(self, d):
            self._d = d

        def model_dump(self):
            return self._d

    import app.automation.engine as E

    E.SETTLE_S = 0  # אל תשהה בבדיקה

    def run(succeed_on, tries=3):
        s = FakeSession(succeed_on)
        tr: list = []
        ok, _ = asyncio.run(
            act_verified(
                s,
                action="do",
                read_instruction="r",
                read_schema={},
                ok=lambda st: st.get("val") == "yes",
                observe_for="el",
                tries=tries,
                trace=tr,
            )
        )
        return ok, s, tr

    # מצליח בניסיון הראשון → act אחד, בלי observe, trace באורך 1
    ok, s, tr = run(succeed_on=1)
    assert ok and s.acts == 1 and s.observes == 0 and len(tr) == 1, (ok, s.acts, s.observes, tr)

    # מצליח רק בניסיון 2 → escalate ל-observe→act בניסיון השני
    ok, s, tr = run(succeed_on=2)
    assert ok and s.acts == 2 and s.observes == 1 and tr[-1]["how"] == "observe-act", (
        s.acts,
        s.observes,
        tr,
    )

    # אף פעם לא מצליח → נכשל אחרי tries, בלי לתקוע
    ok, s, tr = run(succeed_on=0, tries=3)
    assert not ok and s.acts == 3 and len(tr) == 3, (ok, s.acts, len(tr))

    print("engine.demo OK")


if __name__ == "__main__":
    demo()
