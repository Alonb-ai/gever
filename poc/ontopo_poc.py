"""
שלב 0 — PoC: האם Browserbase + Stagehand עוברים את Ontopo?

זה השער go/no-go של כל הפרויקט. המטרה היחידה: להוכיח שאפשר להגיע
לעמוד מסעדה ב-Ontopo ולהתקדם בזרימת הזמנת שולחן — בקוד, בלי דפדפן ידני.

הרצה:
    cp .env.example .env   # ומלא BROWSERBASE_API_KEY + MODEL_API_KEY
    uv pip install stagehand python-dotenv
    python poc/ontopo_poc.py

מבוסס על Stagehand Python SDK v3: https://docs.stagehand.dev/v3/sdk/python
"""

import asyncio
import os

from dotenv import load_dotenv
from stagehand import AsyncStagehand

load_dotenv()

# פרטי הבדיקה — שנה לפי המסעדה/תאריך שאתה רוצה לבדוק.
RESTAURANT_QUERY = "אבו חסן"          # שם המסעדה לחיפוש ב-Ontopo
PARTY_SIZE = 2
TARGET_TIME = "20:00"
# חשוב: בשלב ה-PoC אנחנו לא לוחצים "אשר סופית" כדי לא ליצור הזמנה אמיתית.
# המטרה היא להגיע עד מסך בחירת השעה/אישור ולוודא שהזרימה עוברת.
DRY_RUN = True


async def main() -> None:
    if not os.getenv("BROWSERBASE_API_KEY") or not os.getenv("MODEL_API_KEY"):
        raise SystemExit(
            "חסר BROWSERBASE_API_KEY או MODEL_API_KEY ב-.env — מלא אותם ונסה שוב."
        )

    client = AsyncStagehand(
        browserbase_api_key=os.getenv("BROWSERBASE_API_KEY"),
        browserbase_project_id=os.getenv("BROWSERBASE_PROJECT_ID") or None,
        model_api_key=os.getenv("MODEL_API_KEY"),
    )
    session = await client.sessions.start(
        model_name=os.getenv("MODEL_NAME", "google/gemini-2.5-pro"),
        system_prompt="אתה מבצע פעולות באתרים בעברית, בזהירות ובדייקנות.",
    )

    try:
        print("→ נכנס ל-Ontopo...")
        await session.navigate(url="https://ontopo.com/he/il")

        print(f"→ מחפש מסעדה: {RESTAURANT_QUERY}")
        await session.act(input=f"חפש את המסעדה '{RESTAURANT_QUERY}' ובחר אותה מהתוצאות")

        print(f"→ מגדיר הזמנה: {PARTY_SIZE} סועדים, שעה {TARGET_TIME}")
        await session.act(input=f"בחר {PARTY_SIZE} סועדים")
        await session.act(input=f"בחר את השעה {TARGET_TIME} הקרובה ביותר הזמינה")

        # מוודאים מה ראינו על המסך — הוכחה שהגענו למסך בחירת זמן/שולחן.
        result = await session.extract(
            instruction="extract the available booking times and the restaurant name shown",
            schema={
                "type": "object",
                "properties": {
                    "restaurant": {"type": "string"},
                    "available_times": {"type": "array", "items": {"type": "string"}},
                },
            },
        )
        print("✅ הגענו למסך הזמנה. מה ש-Stagehand קרא מהדף:")
        try:
            print(result.model_dump())
        except Exception:
            print(result)

        if DRY_RUN:
            print("\n[DRY_RUN] לא מאשר הזמנה אמיתית. שלב 0 עבר אם הגענו לכאן.")
        else:
            await session.act(input="אשר את ההזמנה")
            print("✅ הזמנה אושרה.")

    finally:
        await session.end()


if __name__ == "__main__":
    asyncio.run(main())
