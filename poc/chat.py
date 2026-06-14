"""
צ'אט אינטראקטיבי עם גבר — ממשק ניסוי מקומי (לפני WhatsApp).

מדבר עם אישיות גבר דרך Gemini, רב-תורי. זה רק שכבת השיחה — הוא *מדבר*
כמו גבר אבל עדיין לא מבצע פעולות (ביצוע = ה-PoC של Ontopo, בנפרד).

הרצה:
    .venv/bin/python poc/chat.py            # ניטרלי
    .venv/bin/python poc/chat.py male       # פנייה בזכר
    .venv/bin/python poc/chat.py female     # פנייה בנקבה
    (Ctrl-C / Ctrl-D ליציאה)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.llm.intent import SYSTEM_PROMPT, character_leaks, gender_line

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def main() -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("חסר GEMINI_API_KEY ב-.env")

    gender = sys.argv[1].strip().lower() if len(sys.argv) > 1 else None
    system = SYSTEM_PROMPT + "\n\n" + gender_line(gender)

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.8),
    )

    print("— מדבר עם גבר. שלח לו משימה. (Ctrl-C ליציאה) —\n")
    while True:
        try:
            msg = input("אתה:  ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nלהתראות 🤙")
            return
        if not msg:
            continue
        reply = chat.send_message(msg).text.strip()
        print(f"גבר:  {reply}\n")
        leaks = character_leaks(reply)
        if leaks:
            print(f"  ⚠️ שבירת דמות: {leaks}\n")


if __name__ == "__main__":
    main()
