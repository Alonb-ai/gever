"""
שלב fallback: ה־rung העמוק ביותר בסולם של act_verified.

כשהסולם הדטרמיניסטי (blind act → observe→act) מתרוקן על *צעד אחד* תקוע, מוסרים את
אותו sub_goal יחיד ל-Stagehand agent (session.execute) שיתכנן וירפא רק אותו, ואז
מאמתים את מצב-העסק *סמנטית* דרך engine.extract + ה-ok של הקורא. לעולם לא סומכים על
data.result.success (הדיווח-העצמי של הסוכן) כהוכחה — ok מחליט.

בטיחות מבנית: הסוכן מקבל רק את הצעד-התקוע, אף פעם לא את צעד האישור/החיוב. ה-submit
נשאר שורה דטרמיניסטית נפרדת ב-playbook, אחרי אישור-אדם. לכן אין כאן keyword-scan.

SDK: stagehand==3.21.0 — AsyncSession.execute קיים; אין session.agent() ואין
session.replay() (אומת בintrospection: AttributeError).
"""

import logging
from typing import Any, Callable

from app.automation import engine
from app.config import settings

log = logging.getLogger("gever")

AGENT_MAX_STEPS = 6  # תקרת-צעדים קשיחה לצעד תקוע אחד — בקרת-התקציב היחידה.


async def run_agent_step(
    session,
    sub_goal: str,
    ok: Callable[[dict], Any],
    *,
    read_instruction: str,
    read_schema: dict,
    trace: list | None = None,
) -> tuple[bool, dict]:
    """
    מוסר sub_goal יחיד ל-Stagehand agent (session.execute), ואז מאמת סמנטית דרך
    engine.extract + ok(state). מחזיר (ok_passed, state). ok הוא הפסיקה — *לא*
    data.result.success. רושם usage ל-trace. הסוכן מרפא רק את הצעד הזה, לעולם לא
    מגיע לצעד האישור.
    """
    self_reported = False
    usage: dict = {}
    try:
        resp = await session.execute(
            agent_config={
                "mode": "dom",  # hardcoded; hybrid/cua נדחו
                "model": {"model_name": settings.model_name},  # נהג קיים, בלי knob חדש
            },
            execute_options={
                "instruction": sub_goal,  # הצעד התקוע היחיד, למשל "בחר N סועדים"
                "max_steps": AGENT_MAX_STEPS,
                "use_search": False,  # בלי גלישת-חיפוש באמצע הזמנה
            },
        )
        result = (resp.model_dump().get("data") or {}).get("result") or {}
        self_reported = bool(result.get("success"))
        usage = result.get("usage") or {}
        log.info("agent step '%s' self_reported=%s usage=%s", sub_goal, self_reported, usage)
    except Exception as exc:  # noqa: BLE001 — execute נכשל → כישלון כן, ה-playbook מדווח
        log.warning("agent execute '%s' raised: %s", sub_goal, exc)

    # אימות סמנטי: מצב-העסק האמיתי, לא הדיווח-העצמי של הסוכן.
    await engine.settle()
    state = await engine.extract(session, read_instruction, read_schema)
    good = bool(ok(state))
    if trace is not None:
        trace.append(
            {
                "action": sub_goal,
                "how": "agent",
                "self_reported": self_reported,
                "ok": good,
                "usage": usage,
                "state": state,
            }
        )
    return good, state


def demo() -> None:
    """self-check עם session מזויף: דיווח-עצמי success אך ok נכשל → (False)."""

    class _Resp:
        def __init__(self, d):
            self._d = d

        def model_dump(self):
            return self._d

    class FakeSession:
        """execute מחזיר self-reported success; extract מחזיר state לפי healed."""

        def __init__(self, healed: bool):
            self.healed = healed
            self.executes = 0

        async def execute(self, *, agent_config, execute_options):
            self.executes += 1
            return _Resp(
                {
                    "data": {
                        "result": {
                            "success": True,  # דיווח-עצמי תמיד חיובי — לא הוכחה
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        }
                    }
                }
            )

        async def extract(self, *, instruction, schema):
            val = "yes" if self.healed else "no"
            return _Resp({"data": {"result": {"val": val}}})

    import asyncio

    engine.SETTLE_S = 0

    def run(healed):
        s = FakeSession(healed)
        tr: list = []
        passed, _ = asyncio.run(
            run_agent_step(
                s,
                "בחר 4 סועדים",
                lambda st: st.get("val") == "yes",
                read_instruction="r",
                read_schema={},
                trace=tr,
            )
        )
        return passed, s, tr

    # הסוכן ריפא → ok עובר → (True), usage נרשם ל-trace
    passed, s, tr = run(healed=True)
    assert passed and s.executes == 1 and tr[-1]["usage"]["input_tokens"] == 10, (passed, tr)

    # הסוכן דיווח success אך ok נכשל → (False) — האימות הסמנטי מנצח
    passed, s, tr = run(healed=False)
    assert not passed and tr[-1]["self_reported"] is True and tr[-1]["ok"] is False, (passed, tr)

    print("agent.demo OK")


if __name__ == "__main__":
    demo()
