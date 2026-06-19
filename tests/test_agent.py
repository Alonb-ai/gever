"""run_agent_step — ה-rung העמוק ביותר בסולם act_verified (session מזויף, בלי רשת)."""

import app.automation.engine as engine
from app.automation.agent import demo, run_agent_step
from app.automation.engine import act_verified


class _Resp:
    def __init__(self, d):
        self._d = d

    def model_dump(self):
        return self._d


class FakeSession:
    """
    מודד מתי כל שכבה רצה. extract מחזיר val=='yes' רק אחרי שה-agent (execute) רץ
    אם agent_heals=True. self-reported success תמיד True — לבדוק שזה לא נחשב הוכחה.
    """

    def __init__(self, *, agent_heals: bool):
        self.agent_heals = agent_heals
        self.acts = 0
        self.observes = 0
        self.executes = 0

    async def act(self, *, input):  # noqa: A002
        self.acts += 1

    async def observe(self, *, instruction):
        self.observes += 1
        return _Resp(
            {"data": {"result": [{"description": "d", "selector": "s", "method": "click"}]}}
        )

    async def execute(self, *, agent_config, execute_options):
        self.executes += 1
        return _Resp(
            {
                "data": {
                    "result": {
                        "success": True,  # דיווח-עצמי תמיד חיובי — לעולם לא הוכחה
                        "usage": {"input_tokens": 7, "output_tokens": 3},
                    }
                }
            }
        )

    async def extract(self, *, instruction, schema):
        good = self.agent_heals and self.executes >= 1
        return _Resp({"data": {"result": {"val": "yes" if good else "no"}}})


def _run_ladder(session):
    import asyncio

    engine.SETTLE_S = 0
    tr: list = []
    passed, state = asyncio.run(
        act_verified(
            session,
            action="בחר 4 סועדים",
            read_instruction="r",
            read_schema={},
            ok=lambda st: st.get("val") == "yes",
            observe_for="el",
            trace=tr,
        )
    )
    return passed, state, tr


def test_agent_fires_only_after_ladder_exhausted():
    # הסולם הדטרמיניסטי (3 ניסיונות) נכשל, אז ה-agent רץ פעם אחת ומרפא → (True).
    s = FakeSession(agent_heals=True)
    passed, _, tr = _run_ladder(s)
    assert passed is True
    assert s.acts == 3, "ה-agent חייב לרוץ רק אחרי שכל 3 הניסיונות הדטרמיניסטיים מוצו"
    assert s.executes == 1, "execute רץ פעם אחת בלבד, אחרי הסולם"
    assert tr[-1]["how"] == "agent" and tr[-1]["ok"] is True
    assert tr[-1]["usage"]["input_tokens"] == 7, "usage נרשם ל-trace"


def test_self_reported_success_with_failing_ok_is_failure():
    # ה-agent מדווח success=True, אבל ok נכשל → התוצאה FAILURE (אימות סמנטי מנצח).
    s = FakeSession(agent_heals=False)
    passed, _, tr = _run_ladder(s)
    assert passed is False, "data.result.success לא נחשב הוכחה — ok הוא הפסיקה"
    assert s.executes == 1
    assert tr[-1]["self_reported"] is True and tr[-1]["ok"] is False


def test_run_agent_step_direct_semantic_verify():
    # קריאה ישירה: self-reported success אך ok נכשל → (False, state).
    import asyncio

    engine.SETTLE_S = 0
    s = FakeSession(agent_heals=False)
    passed, state = asyncio.run(
        run_agent_step(
            s,
            "בחר 4 סועדים",
            lambda st: st.get("val") == "yes",
            read_instruction="r",
            read_schema={},
        )
    )
    assert passed is False and state == {"val": "no"} and s.executes == 1


def test_agent_demo():
    demo()
