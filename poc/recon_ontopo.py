"""recon: נוהג בזרימת ההזמנה של Ontopo עד *רגע לפני* האישור הסופי (לא מאשר!) ומתעד —
אישור התנאים → 'המשך' → שלב פרטי הקשר: שם/מייל/טלפון בלבד או גם אשראי? יש כפתור
אישור סופי? לאבחון האם אפשר לסגור בלי כרטיס (המסעדה מתקשרת לכרטיס בנפרד).

הרצה (מהריפו הראשי, בשביל .env):
    .venv/bin/python <worktree>/poc/recon_ontopo.py "הדסון לילינבלום" "26" "21:30"
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from stagehand import AsyncStagehand

from app.automation import engine
from app.automation.resolve import resolve_ontopo_url

load_dotenv()

STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "step_title": {"type": "string"},
        "name_input_present": {"type": "boolean"},
        "email_input_present": {"type": "boolean"},
        "phone_input_present": {"type": "boolean"},
        "credit_card_fields_present": {"type": "boolean"},
        "credit_card_required_now": {"type": "boolean"},
        "final_confirm_button_label": {"type": "string"},
        "notes": {"type": "string"},
    },
}


async def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "הדסון לילינבלום"
    date = sys.argv[2] if len(sys.argv) > 2 else "26"
    time = sys.argv[3] if len(sys.argv) > 3 else "21:30"

    found = await resolve_ontopo_url(name)
    print(f"→ {name}: status={found['status']} url={found['url']}", flush=True)
    if not found["url"]:
        return

    client = AsyncStagehand(
        browserbase_api_key=os.getenv("BROWSERBASE_API_KEY"),
        browserbase_project_id=os.getenv("BROWSERBASE_PROJECT_ID") or None,
        model_api_key=os.getenv("MODEL_API_KEY"),
    )
    session = await client.sessions.start(
        model_name=os.getenv("MODEL_NAME", "google/gemini-3-flash-preview"),
        dom_settle_timeout_ms=3000,
    )
    try:
        await session.navigate(url=found["url"])
        await engine.settle(2)
        await session.act(input="בחר 2 סועדים")
        await session.act(input=f"פתח את בורר התאריך ובחר את היום {date}; גלול בלוח אם צריך")
        await session.act(input=f"פתח את בורר השעה וגלול עד {time} ואז בחר אותה")
        await session.act(input="לחץ על הכפתור 'מצאו לי שולחן'")
        await engine.settle(2)
        await session.act(input="בחר את אחת השעות הזמינות שמופיעות בתוצאות")
        await engine.settle(2)

        # מסך הסיכום ('פרטי הזמנה' + 'חשוב לדעת'): גוללים בקופסת התנאים ומסמנים את כולן,
        # מאמתים שהכפתור 'המשך' נפתח (אחרת הוא חסום), ורק אז לוחצים.
        cond = {"properties": {"checkboxes_total": {"type": "integer"},
                               "checkboxes_checked": {"type": "integer"},
                               "continue_enabled": {"type": "boolean"}}, "type": "object"}
        for i in range(3):
            await session.act(input="גלול עד הסוף בתוך קופסת 'חשוב לדעת' כדי לחשוף את כל התנאים")
            await session.act(input="סמן (לחץ) כל תיבת סימון של תנאי שעדיין לא מסומנת בקופסת 'חשוב לדעת'")
            st = await engine.extract(
                session,
                "In the 'חשוב לדעת' terms box: how many checkboxes exist, how many are "
                "currently checked, and is the 'המשך' continue button enabled (not greyed out)?",
                cond,
            )
            print(f"  conditions try {i + 1}: {json.dumps(st, ensure_ascii=False)}", flush=True)
            if st.get("continue_enabled"):
                break
            await engine.settle(1)

        await session.act(input="לחץ על הכפתור 'המשך'")
        await engine.settle(2)

        print("\n=== אחרי 'המשך' — שלב פרטי הקשר ===", flush=True)
        before = await engine.extract(
            session,
            "Describe this step. Is there a NAME input, an EMAIL input, a PHONE input? "
            "Are there CREDIT CARD fields (card number/expiry/cvv) and is a card required "
            "to continue right now? What is the label of the main button to finalize the booking?",
            STEP_SCHEMA,
        )
        print(json.dumps(before, ensure_ascii=False, indent=2), flush=True)

        # ממלאים פרטי קשר (אם יש שדות) ובודקים שוב — בלי ללחוץ אישור סופי
        await session.act(input="מלא את שם המזמין: אלון")
        await session.act(input="מלא אימייל: abazak@gmail.com")
        await session.act(input="מלא טלפון: 0542773331")
        await engine.settle(1)

        print("\n=== אחרי מילוי שם/מייל/טלפון (לפני אישור סופי, לא לוחצים!) ===", flush=True)
        after = await engine.extract(
            session,
            "After filling name/email/phone: is the booking ready to be confirmed with just "
            "these details, or is a credit card still required before confirming? What does "
            "the final confirm button say, and what phone number is shown in the phone field now?",
            {
                "type": "object",
                "properties": {
                    "ready_to_confirm_without_card": {"type": "boolean"},
                    "credit_card_still_required": {"type": "boolean"},
                    "final_confirm_button_label": {"type": "string"},
                    "phone_field_value": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
        )
        print(json.dumps(after, ensure_ascii=False, indent=2), flush=True)
        print("\n(לא נלחץ אישור סופי — recon בלבד)", flush=True)
    finally:
        await session.end()


if __name__ == "__main__":
    asyncio.run(main())
