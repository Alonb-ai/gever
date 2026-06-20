"""recon: נוהג בזרימת ההזמנה של Ontopo עד שלב פרטי הקשר (בלי לאשר) ומתעד אותו —
האם יש שדה שם/טלפון, האם דורש התחברות/OTP, ומה כפתור ההמשך. לאבחון באג הטלפון.

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

CONTACT_SCHEMA = {
    "type": "object",
    "properties": {
        "name_input_present": {"type": "boolean"},
        "phone_input_present": {"type": "boolean"},
        "phone_field_value": {"type": "string"},
        "login_or_signin_required": {"type": "boolean"},
        "otp_or_code_field_present": {"type": "boolean"},
        "primary_button_label": {"type": "string"},
        "step_text": {"type": "string"},
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
        await session.act(
            input=f"פתח את בורר התאריך ובחר את היום {date}; גלול בלוח אם צריך"
        )
        await session.act(
            input=f"פתח את בורר השעה וגלול עד {time} ואז בחר אותה"
        )
        await session.act(input="לחץ על הכפתור 'מצאו לי שולחן'")
        await engine.settle(2)

        # נבחר את ה-slot הראשון הזמין כדי להגיע לשלב פרטי הקשר
        await session.act(input="בחר את אחת השעות הזמינות שמופיעות בתוצאות")
        await engine.settle(2)

        print("\n=== שלב פרטי הקשר (אחרי בחירת slot) ===", flush=True)
        info = await engine.extract(
            session,
            "We are at the step after choosing a time slot. Describe it: is there a "
            "NAME text input and a PHONE/מספר טלפון text input to fill? Does it require "
            "signing in / login / 'התחברות' or a verification CODE/OTP/'קוד אימות'? "
            "What is the label of the main button to proceed? Give the value currently "
            "shown in the phone field if any.",
            CONTACT_SCHEMA,
        )
        print(json.dumps(info, ensure_ascii=False, indent=2), flush=True)
    finally:
        await session.end()


if __name__ == "__main__":
    asyncio.run(main())
