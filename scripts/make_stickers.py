"""יצירת סטיקרים סטטיים של גבר — webp 512x512 ≤100KB (דרישות Meta לסטיקר סטטי).

חד-פעמי בפיתוח (Pillow ב-venv המקומי): טקסט עברי קצר בסגנון הדמות על כרטיס
צבעוני נקי, נשמר ל-assets/stickers/. הרצה חוזרת דורסת — הקבצים עצמם בקומיט.

    .venv/bin/python scripts/make_stickers.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

OUT = Path(__file__).resolve().parent.parent / "assets" / "stickers"
SIZE = 512

# (קובץ, טקסט, צבע כרטיס) — טקסטים קצרים בסגנון הדמות
STICKERS = [
    ("sagur.webp", "סגור", "#1fA97a"),
    ("yesh.webp", "יש!", "#e8590c"),
    ("alia.webp", "עליה", "#1971c2"),
    ("bodek.webp", "בודק...", "#5f3dc4"),
    ("al_ze.webp", "על זה", "#c2255c"),
]

# פונט עברי עבה שקיים ב-macOS; הראשון שנמצא מנצח
FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Hebrew Bold.ttf",
    "/System/Library/Fonts/Supplemental/ArialHB.ttc",
    "/System/Library/Fonts/SFHebrew.ttf",
    "/Library/Fonts/Arial Hebrew Bold.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise SystemExit("לא נמצא פונט עברי — עדכן את FONTS")


def _display(text: str) -> str:
    """בלי libraqm פיל מצייר בסדר לוגי (עברית יוצאת הפוכה) — היפוך ידני מספיק
    לטקסט עברי-בלבד קצר."""
    return text if features.check("raqm") else text[::-1]


def make(name: str, text: str, color: str) -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # כרטיס מעוגל עם מסגרת לבנה — קריא על כל רקע צ'אט
    d.rounded_rectangle([16, 96, SIZE - 16, SIZE - 96], radius=72, fill=color)
    d.rounded_rectangle([16, 96, SIZE - 16, SIZE - 96], radius=72, outline="white", width=14)
    # גודל פונט שממלא את הכרטיס בלי לגלוש
    shown = _display(text)
    size = 190
    while size > 40:
        f = _font(size)
        w = d.textlength(shown, font=f)
        if w <= SIZE - 110:
            break
        size -= 10
    d.text((SIZE / 2, SIZE / 2), shown, font=f, fill="white", anchor="mm")
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / name, "WEBP", quality=90, method=6)
    kb = (OUT / name).stat().st_size / 1024
    assert kb <= 100, f"{name}: {kb:.0f}KB חורג ממגבלת הסטיקר הסטטי"
    print(f"{name}: {kb:.0f}KB")


if __name__ == "__main__":
    for name, text, color in STICKERS:
        make(name, text, color)
