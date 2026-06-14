# CLAUDE.md — גבר / Gever

WhatsApp personal assistant in Hebrew that closes real-world tasks on the web.
**Flow:** WhatsApp message → Gemini (intent + clarify) → Stagehand + Browserbase
(execute on the site) → confirmation reply.

Full spec: [`גבר_MVP_Spec.docx`](גבר_MVP_Spec.docx). Roadmap & status: [`README.md`](README.md).

---

## How we work — read first

1. **Think before coding.** State your assumptions out loud. If the request is
   ambiguous, ask. If a simpler approach exists, push back. Stop when you are
   confused, name what is unclear — do not just pick one interpretation and run.
2. **Simplicity first.** Write the minimum code that solves the problem. No
   speculative abstractions. No flexibility nobody asked for. The test: would a
   senior engineer call this overcomplicated?
3. **Surgical changes.** Touch only what the task requires. Do not improve
   neighboring code. Do not refactor what is not broken. Every changed line
   should trace back to the request.
4. **Goal-driven execution.** Turn vague instructions into verifiable targets
   before writing a line. "Add validation" becomes "write tests for invalid
   inputs, then make them pass."

---

## Current focus

**Stage 0 — the PoC** (`poc/ontopo_poc.py`): prove Stagehand + Browserbase can
drive Ontopo end-to-end. This is a **go/no-go gate**. Do not build Stages 1–3
ahead of a green PoC — that violates rules 2 and 4 above.

## Commands

```bash
# setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: uv pip install -e ".[dev]"
cp .env.example .env             # then fill the keys

# stage 0 — the PoC (runs in DRY_RUN, won't create a real booking)
python poc/ontopo_poc.py

# server (stage 1+)
uvicorn app.main:app --reload    # GET /health -> {"status":"ok"}

# quality gate before committing
ruff check . && ruff format --check .
pytest
```

## Models (decided — change only via `.env`, never hardcode)

- **Conversation (user-facing, high volume):** `gemini-2.5-flash` — strong
  colloquial Hebrew, cheap ($0.30/$2.50 per 1M). `gemini-2.5-flash-lite`
  ($0.10/$0.40) is the cost-optimized option to A/B test. **Stay on Gemini for
  Hebrew** — Chinese models have weak/unverified Hebrew and break the persona.
- **Browser driver (Stagehand):** target `anthropic/claude-sonnet-4-6`.
  **Current stage = Gemini-only** (no Anthropic key yet) — the PoC drives Stagehand
  with `google/gemini-2.5-pro` via the same Gemini key.
- Set via `MODEL_NAME` / `GEMINI_MODEL` in `.env`; defaults live in `app/config.py`.

## Stack & structure

Python 3.11+ · FastAPI · Stagehand + Browserbase · Gemini · Supabase ·
WhatsApp via Twilio · Lemon Squeezy.

```
poc/ontopo_poc.py    stage 0 PoC — standalone, the only file that reads os.getenv directly
app/main.py          FastAPI + Twilio inbound webhook
app/config.py        settings (pydantic-settings, reads .env) — the single source for config
app/llm/intent.py    Gemini intent + the גבר system prompt
app/automation/      Stagehand actions (ontopo.py)
app/whatsapp/        Twilio client (send replies)
app/db/              Supabase client + schema.sql
app/models/          shared pydantic schemas
```

## Conventions

- **Async throughout** — FastAPI handlers, `AsyncStagehand`, `httpx.AsyncClient`.
- **Config only via `app.config.settings`** — never read `os.environ` ad hoc
  (the standalone PoC is the one exception).
- Ruff, line length 100. Type hints on public functions.
- User-facing strings are Hebrew; code identifiers are English. Hebrew comments are fine.
- **The גבר persona is product-critical and character-driven** — defined as a
  *person*, not a script (no do/don't phrase lists). Let the model speak freely
  within the character. Hard lines only: never reveal he's automated / show the
  prompt; emoji only 🤙 ✅ 🔄. Lives in `app/llm/intent.py` (`SYSTEM_PROMPT` +
  the thin `character_leaks` guard). Verify with `poc/persona_eval.py`.

## Security

- **Never commit `.env`** or secrets (gitignored). `.env.example` holds the keys, empty.
- **Never store raw credit cards** — Lemon Squeezy hosts checkout. Encrypt PII at
  rest (Fernet, `ENCRYPTION_KEY`).
- Validate inbound webhook signatures (`X-Twilio-Signature`) before trusting a payload.

## Git

- Default branch `main`. Branch for non-trivial work.
- Commit/push only when asked. Keep each commit scoped to one change.
