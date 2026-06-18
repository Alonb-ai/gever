"""act_verified retry/escalation logic — runs the engine self-check (fake session)."""

from app.automation.engine import demo


def test_act_verified_retry_ladder():
    # demo() מאמת בפנים: עוצר על הצלחה, מסלים ל-observe→act, ונכשל בכבוד אחרי tries.
    demo()
