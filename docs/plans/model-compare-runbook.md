# Runbook — השוואת מודלים (נווט + שיחה), יולי 2026

קו הבסיס המלא: `docs/plans/nav-baseline-2026-07.md` (ענף charming-banzai, ריצת 17.07):
**נווט 5/7 (71%) הגעה לסיכום/קיר-כרטיס · ~4.5 דק' למשימה מוצלחת · persona 15/16.**

## לפני שמריצים

- מפתח הספק ב-`.env` לפי קידומת המודל:
  `gemini-*` → `GEMINI_API_KEY` (קיים) · `claude-*` → `ANTHROPIC_API_KEY` ·
  `gpt-*` → `OPENAI_API_KEY` · `bu-*` → `BROWSER_USE_API_KEY`.
- **חלון שקט** — אף ריצה חיה אחרת במקביל (בנצ' v3 הורעל: timeouts/broken_page).
- **מועמד אחד בכל פעם**, סדרתית. סבב נווט ≈ 30–50 דק'.
- אותם פרטי intake בדיוק — הסט קבוע בתוך `poc/nav_bench.py`, לא לגעת בו בין ריצות.
- `DRY_RUN=true` נשאר (שום הזמנה לא נסגרת).

## נווט (browser-use)

```bash
MODEL_NAME=<model> .venv/bin/python poc/nav_bench.py 2>&1 | tee /tmp/nav_<model>.md
```

## שיחה (persona)

```bash
PERSONA_MODEL=<model> .venv/bin/python poc/persona_eval.py 2>&1 | tee /tmp/persona_<model>.log
```

השופט תמיד Gemini (`GEMINI_MODEL`) — שיפוט אחיד בין מועמדים. למועמדי `claude-*`/`gpt-*`
בדיקת ה-extract מדולגת (structured output של Gemini) — הציון מתוך 15, לא 16.

## טבלת תוצאות

| מודל | נווט: הצלחות | ממוצע דק'/משימה | persona | הערות |
|---|---|---|---|---|
| **baseline: google/gemini-3-flash-preview** | **5/7 (71%)** | **~4.5** | **15/16** | ריצת 17.07 |
| gemini-3-1-pro | | | | |
| bu-2-0 | | | | |
| claude-haiku-4-5 | | | | |
| gpt-5.4-mini | | | | |
| gemini-3.1-flash-lite | | | | |
