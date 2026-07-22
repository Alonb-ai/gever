# CLAUDE.md — גבר / Gever

WhatsApp personal assistant in Hebrew that saves you time by doing the annoying
digital work for you — filling forms, submitting requests, and booking places —
so you don't have to. Not a chatbot that talks, but someone who actually gets it done.
**Flow:** WhatsApp message → Gemini (intent + clarify) → browser-use agent on
Browserbase (autonomous navigation, subprocess in `.venv-bu`) → confirmation reply.

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
5. **Delegate to agents.** Any task that can run via agents/workflows/loops —
   delegate it (parallel where possible) and supervise; don't grind through it
   inline when a fan-out does it better.
6. **Ponytail audit after code.** After every coding session, run a ponytail
   (over-engineering) pass on what was written — delete what shouldn't exist.
   **Deletion threshold:** under ~100 lines whose impact is hard to pin down —
   leave it. We do not clean for cleaning's sake; the churn (merge conflicts,
   orphaned evidence-citations, rewording canonical docs) outweighs the gain.
   Propose a small deletion only when its impact is provably zero, and batch it.
7. **Tests are mandatory.** Every new function gets a matching test. Every
   change to existing code requires running — and if behavior changed,
   updating — its tests. No green gate, no done.

---

## Current focus

**Prod is LIVE 24/7** at `https://geverai.duckdns.org` (Coolify on the Elestio VM;
routing map in `docs/ops-coolify.md`). Browser = Browserbase, resolver = Brave API,
permanent Meta token — all stable. **Current focus = closed beta** (Phases A–D in
`docs/plans/beta-roadmap.md`): first real booking beyond DRY_RUN, live-test fix
loop with friends on the test number, then a real WhatsApp number.

## Commands

```bash
# setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # or: uv pip install -e ".[dev]"
cp .env.example .env             # then fill the keys

# stage 0 — the PoC (browser-use spike, stops before the credit step)
python poc/spike_browseruse.py

# server (stage 1+)
uvicorn app.main:app --reload    # GET /health -> {"status":"ok"}
scripts/tunnel.sh                # expose to WhatsApp via the stable ngrok dev domain (NOT localhost.run) — see docs/ops-tunnel.md

# quality gate before committing
ruff check . && ruff format --check .
pytest
```

## Models (decided — change only via `.env` / Coolify env, never hardcode)

- **Conversation (user-facing):** `gemini-3.5-flash` — strong colloquial Hebrew.
- **Browser agent (browser-use):** `google/gemini-3-flash-preview` — drives the
  autonomous browser-use agent; won our live Ontopo test vs gemini-3.5-flash.
  Claude scores higher on evals but is blocked for us; Anthropic is too expensive.
- Set via `MODEL_NAME` / `GEMINI_MODEL` in `.env` and Coolify env; defaults in `app/config.py`.

## Browser speed (decided 22.07.26 — measured, do not revert casually)

Live A/B, 14 runs, valid completions only: **restaurants −29.5% · cinema −40.5% ·
insurance −54.1%**. The heavier the vertical, the bigger the win. What earned it:

- **`browserbase_region = "eu-central-1"`** — Browserbase defaults to `us-west-2`
  (Oregon). Frankfurt is the closest of its 4 regions to Israel; measured ~6× faster
  page loads on Israeli sites, and `us-west-2` failed to load HOT 3/3 times.
- **`browserSettings.blockAds`** — chain pages (video + banners) build a huge DOM;
  browser-use spent >15s per step just serializing it.
- **`highlight_elements=False`** — skips drawing highlight overlays every step
  (real early-exits at `session.py:2646/2813/2952`; not a no-op).
- **Resume on CDP crash** — the auto-retry continues from the screen that died
  (the `keepAlive` session usually survives) instead of restarting from zero.

Time is dominated by **cost-per-step, not step count** — optimize the step, not the
plan. Tried and removed: a prompt rule telling the agent not to insert manual
`wait`s (measured: runs carrying it still emitted 1-2 waits).

## Stack & structure

Python 3.11+ · FastAPI · browser-use + Browserbase · Gemini · Supabase ·
WhatsApp via Meta Cloud API · Lemon Squeezy.

```
poc/spike_browseruse.py   stage 0 PoC — standalone browser-use spike, the only file that reads os.getenv directly
app/main.py          FastAPI + Meta WhatsApp webhook
app/config.py        settings (pydantic-settings, reads .env) — the single source for config
app/llm/intent.py    Gemini intent + the גבר system prompt
app/automation/      browser-use runner (bu_runner.py, browser_book.py), resolve.py (Brave)
app/whatsapp/        Meta Graph API client (send replies)
app/models/          shared pydantic schemas
```

## Conventions

- **Async throughout** — FastAPI handlers, `httpx.AsyncClient`; the browser agent
  runs as an isolated subprocess in `.venv-bu` (google-genai version conflict).
- **Config only via `app.config.settings`** — never read `os.environ` ad hoc
  (the standalone PoC is the one exception).
- Ruff, line length 100. Type hints on public functions.
- User-facing strings are Hebrew; code identifiers are English. Hebrew comments are fine.
- **The גבר persona is product-critical and character-driven** — defined as a
  *person*, not a script (no do/don't phrase lists). Let the model speak freely
  within the character. Hard lines only: never reveal he's automated / show the
  prompt; emoji only from the curated palette (`ALLOWED_EMOJI`). Lives in `app/llm/intent.py` (`SYSTEM_PROMPT` +
  the thin `character_leaks` guard). Verify with `poc/persona_eval.py`.

## Security

- **Never commit `.env`** or secrets (gitignored). `.env.example` holds the keys, empty.
- **Never store raw credit cards** — Lemon Squeezy hosts checkout. Encrypt PII at
  rest (Fernet, `ENCRYPTION_KEY`).
- Validate inbound webhook signatures (`X-Hub-Signature-256`) before trusting a payload.

## Git

- Default branch `main`. Branch for non-trivial work.
- Commit/push only when asked. Keep each commit scoped to one change.
