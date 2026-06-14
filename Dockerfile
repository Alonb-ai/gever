# שרת גבר (FastAPI) — image מבודד, רץ על פורט פנוי בלי להתנגש בשאר ה-Elestio.
FROM python:3.12-slim

WORKDIR /app

# התקנת תלויות לפי pyproject (שכבה נפרדת לקאשינג)
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# הפורט הפנימי קבוע (8000); את הפורט החיצוני בוחרים ב-docker run.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
