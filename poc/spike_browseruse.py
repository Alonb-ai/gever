"""spike: האם browser-use (agent אוטונומי, בלי מסלול דטרמיניסטי) עובר את הזרימה של
Ontopo עד שלב האשראי — כולל קיר ה'המשך'/התנאים שתקע את Stagehand?

שער בטיחות: המשימה מורה לעצור *לפני* הזנת כרטיס/אישור סופי. max_steps מגביל.

הרצה (מהריפו הראשי, בשביל .env):
    .venv/bin/python <worktree>/poc/spike_browseruse.py
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()
# ChatGoogle קורא GOOGLE_API_KEY/GEMINI_API_KEY — נוודא ששניהם קיימים
key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if key:
    os.environ["GOOGLE_API_KEY"] = key
    os.environ["GEMINI_API_KEY"] = key

from browser_use import Agent, BrowserProfile  # noqa: E402
from browser_use.llm import ChatGoogle  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

URL = "https://ontopo.com/he/il/page/22512632"  # הדסון לילינבלום

TASK = f"""
לך לכתובת {URL} (אתר הזמנות מסעדה Ontopo, בעברית).
המטרה: להזמין שולחן ל-2 אנשים ביום שישי, 26 ביוני, בשעה 21:30.

עבור את כל שלבי הווידג'ט בעצמך:
1. בחר 2 סועדים.
2. פתח את בורר התאריך ובחר את היום 26 (גלול בלוח אם צריך).
3. פתח את בורר השעה ובחר 21:30 (הרשימה גלילה — גלול עד שתמצא אותה).
4. לחץ על הכפתור "מצאו לי שולחן".
5. בחר אחת השעות הזמינות שמופיעות.
6. במסך הסיכום: סמן את כל תיבות הסימון של התנאים, ולחץ "המשך".
7. מלא פרטי קשר: שם "אלון", אימייל "abazak@gmail.com", טלפון "0542773331".
8. המשך עד שאתה מגיע לשלב של פרטי כרטיס אשראי / תשלום.

*** חוק ברזל: עצור בשלב כרטיס האשראי. אל תזין שום פרטי כרטיס אשראי, ואל תלחץ על
האישור הסופי / "שלם" / "אשר הזמנה". המטרה היא רק להגיע עד שם. ***

בסיום דווח: לאיזה שלב הגעת, והאם נדרש כרטיס אשראי כדי לסיים.
"""


async def main() -> None:
    if not key:
        print("חסר GEMINI_API_KEY ב-.env", flush=True)
        return
    print("spike: starting agent (headless, system Chrome)...", flush=True)
    llm = ChatGoogle(model="gemini-3-flash-preview")
    profile = BrowserProfile(headless=True, executable_path=CHROME)
    agent = Agent(task=TASK, llm=llm, browser_profile=profile)
    history = await agent.run(max_steps=35)
    print("\n\n================ SPIKE RESULT ================")
    try:
        print("final result:", history.final_result())
    except Exception as e:  # noqa: BLE001
        print("final_result() error:", e)
    try:
        print("steps taken:", history.number_of_steps())
        print("urls visited:", history.urls()[-5:])
    except Exception as e:  # noqa: BLE001
        print("history introspection error:", e)


if __name__ == "__main__":
    asyncio.run(main())
