# שרת גבר (FastAPI) + venv נפרד ל-browser-use.
# הדפדפן רץ ב-Browserbase (חיבור CDP) — אין Chrome ב-image; ב-Coolify מציבים
# BU_BROWSER=browserbase. שני venvs כי browser-use מצמיד google-genai==1.65
# וה-app על 2.x (ראה browser_book.py).
FROM python:3.12-slim

WORKDIR /app

# venv נפרד ל-browser-use (שכבה עצמאית — משתנה רק כשמעדכנים גרסה)
RUN python -m venv /opt/bu-venv && \
    /opt/bu-venv/bin/pip install --no-cache-dir browser-use==0.13.1
ENV BU_VENV_PATH=/opt/bu-venv/bin/python

# תלויות + קוד ה-app. COPY app לפני ה-install מבטל את קאש השכבה בכל דיפלוי —
# מקובל כרגע (build של דקות); אם יציק, לפצל התקנת תלויות לשכבה משלה.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# הפורט הפנימי קבוע (8000); את הפורט החיצוני בוחרים ב-docker run / Coolify.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
