# Migration — replace the deterministic navigation layer with browser-use

## Goal

Rip out the deterministic mechanism (Stagehand playbook + `act_verified` ladder +
agent fallback) and wire the **autonomous** browser-use agent as the navigation
layer, so a real WhatsApp dry-run booking works **end to end with the full גבר
persona**: WhatsApp message → Gemini persona (converse) → browser-use books on
Ontopo (stops before the card/irreversible step) → Gever reports back honestly.

Validated by the spike: browser-use completed the whole Ontopo flow to the card
step in 12 autonomous steps, passing every wall that blocked Stagehand, and
respected a "stop before the card" safety instruction.

## The one hard constraint: the google-genai version clash

`browser-use` **pins `google-genai==1.65`**; our FastAPI app/pipeline needs
`google-genai==2.8` (the `chats.create(history=...)` API we built memory on).
They cannot live in one venv. So browser-use runs **out-of-process**, in its own
venv, behind a thin boundary. This is not optional — it is forced by the pin.

**Chosen boundary: subprocess per booking** (not an HTTP service).
`run_booking` spawns `.venv-bu/bin/python -m automation.bu_runner` with the
booking params as JSON on argv/stdin; the runner runs the agent and prints one
JSON result line to stdout; the app parses it. No long-running service, no IPC
framework, no ports. The booking is already slow (seconds), so a per-call
subprocess cold-start (~2–3 s) is in the noise.

## Pieces

### New

- **`automation/bu_runner.py`** — standalone script, runs in `.venv-bu` (only
  imports `browser_use` + stdlib, **never `app.*`**). Reads a JSON job
  `{url, date, time, party_size, name, email, phone, dry_run, record_dir}`,
  builds a browser-use `Agent` with the booking task (the spike's task,
  parametrized) and the **safety gate baked into the prompt + `max_steps`**
  (stop before entering card / final confirm). Enables recording
  (`record_video_dir`, `generate_gif`, `save_conversation_path`) into
  `record_dir`. Prints `{"success", "stage", "card_required", "message"}`
  as the last stdout line.
  - **Browser layer is configurable** (`BrowserProfile`/`BrowserSession` both
    take `cdp_url` — verified): **local Chrome** (`executable_path`, headless)
    for dev/free, or **Browserbase** (`cdp_url` = a Browserbase session's
    connectUrl) for production, where Browserbase supplies the stealth + captcha
    solving + proxies that local Chrome cannot. Same browser-use agent on top,
    one config switch. browser-use **cannot solve captchas itself** — that is
    exactly what the Browserbase infra layer is for.
- **`app/automation/browser_book.py`** — `async def book_table_bu(...) ->
  ActionResult` (in the app venv). Spawns the runner subprocess
  (`asyncio.create_subprocess_exec`), passes the job, awaits with a timeout
  (reuse `BOOKING_TIMEOUT_S`), parses the JSON result into `ActionResult`. Same
  return shape as the old `book_table`, so the pipeline barely changes.
- **`.venv-bu`** — a dedicated venv: `python3.12 -m venv .venv-bu && .venv-bu/bin/pip
  install browser-use`. Path configurable via settings. Documented in README +
  a `scripts/setup-bu.sh` one-liner. (gitignored like `.venv`.)

### Changed

- **`app/pipeline.py`** — `run_booking` calls `book_table_bu(...)` instead of
  `book_table(...)`. The `converse`/persona/`_truth_note`/`run_commit`/WhatsApp
  loop, memory, profile — **all unchanged**. The DRY_RUN gate stays: browser-use
  stops at the card step; Gever reports "הכל מוכן, נשאר רק כרטיס" honestly.
- **`app/config.py`** — add `bu_venv_path`, `bu_browser` (`local`|`browserbase`),
  `bu_headless`, `bu_chrome_path`, `bu_record_dir`, reuse `model_name` for the
  agent LLM and the existing `browserbase_api_key`/`browserbase_project_id` for
  the `browserbase` mode.

### Removed (the deterministic mechanism Alon wants gone)

- **`app/automation/ontopo.py`** — `book_table` + all the Stagehand helpers
  (`_match_restaurant` etc. move to `resolve.py` if still used by it; resolve
  imports `_is_listing`/`_match_restaurant` from ontopo today — relocate those two
  to `resolve.py` and delete the rest of ontopo.py).
- **`app/automation/engine.py`** — `act_verified`, `_attempt`, `observe_first`,
  `_clean_candidate`, `demo`. **Keep `error_detail` + `settle`** (used by the
  pipeline) — move them to a tiny `automation/util.py` (or keep a 15-line
  engine.py with just those two).
- **`app/automation/agent.py`** — `run_agent_step`. Delete the file.
- **Stagehand** — drop from `pyproject` deps once nothing imports it.
- **Tests** — delete `test_engine.py`, `test_agent.py`. Keep `test_resolve.py`.
  Add a `test_browser_book.py` that mocks the subprocess (feeds a canned JSON
  line) and asserts `book_table_bu` parses it into the right `ActionResult` —
  no live browser in CI.

### Kept untouched

- `resolve.py` (DuckDuckGo name→URL) + `test_resolve.py`.
- `pipeline.py` conversation/persona/memory/profile/truth-note/run_commit.
- `intent.py` persona, `db/memory.py`, `whatsapp/`, the landing page.

## The booking task (the agent prompt)

One parametrized Hebrew template (from the spike): navigate to `url`, pick party
size, date, time (scroll lists), "מצאו לי שולחן", pick the slot, accept all
terms, click המשך, fill name/email/phone, continue **until the credit-card
step**, then **STOP — never enter card details, never final-confirm** (the iron
rule, enforced both in the prompt and by leaving the card/confirm out of reach).
Returns the stage reached + whether a card is required.

## Flow after migration (unchanged from the user's POV)

```
WhatsApp "תזמין הדסון לילינבלום שישי 21:30 לשניים"
 → converse (Gemini persona) → ready
 → run_booking → resolve(name)→url → book_table_bu(subprocess)
      → browser-use agent drives Ontopo to the card step, stops, records
 → ActionResult → Gever (persona): "הכל מוכן אח שלי, שולחן ל-2 שישי 21:30,
    נשאר רק כרטיס אשראי לאשר" (DRY_RUN — nothing committed)
```

## Open questions

1. **Recording retention** — cap `bu_record_dir` size / prune old runs? Default:
   keep last N runs, prune the rest (cheap).
2. **Agent LLM** — `gemini-3-flash-preview` (spike used it, worked). Keep, or a
   stronger model for the gnarly forms (insurance) later? Default: flash now.
3. **Production browser** — RESOLVED: configurable. Local headless Chrome for
   dev (free); browser-use → **Browserbase via `cdp_url`** for production
   (stealth + captcha + proxies). Keep the Browserbase subscription — it is the
   captcha/anti-bot layer browser-use rides on, not a redundant one. Dev defaults
   to local; flip to `browserbase` when bot-checks appear or for the live
   product.

## Build steps (ordered)

1. `.venv-bu` setup + `scripts/setup-bu.sh` + README note. Verify the spike runs
   from `.venv-bu` (not the polluted `.venv`).
2. `automation/bu_runner.py` — generalize the spike into a JSON-in/JSON-out
   runner with the safety gate + recording.
3. `app/automation/browser_book.py` — `book_table_bu` subprocess wrapper →
   `ActionResult`. `test_browser_book.py` (mock subprocess).
4. Relocate `error_detail`/`settle` (+ `_is_listing`/`_match_restaurant` for
   resolve), then delete `engine.py` act-ladder / `agent.py` / `ontopo.book_table`.
5. `pipeline.run_booking` → `book_table_bu`. Drop Stagehand from deps.
6. `ruff` + `pytest` (engine/agent tests gone; resolve + memory + pipeline green).
7. Live WhatsApp dry-run with Alon: message Gever → real browser-use booking to
   the card step → persona reply. Watch the recording.

---

## Ponytail review (over-engineering)

The spine is right and lean: subprocess boundary (not an HTTP service), delete
the deterministic mechanism wholesale, change one line in `run_booking`, keep
everything above the navigation layer untouched. The `ActionResult` return shape
means the pipeline barely moves. Good. Findings, biggest cut first:

**1. `bu_runner` as `-m automation.bu_runner` is wrong — use a plain script path.**
The `.venv-bu` venv has no `app`/`automation` package installed, so `-m
automation.bu_runner` won't resolve. **Leaner:** a standalone file invoked by path
— `.venv-bu/bin/python automation/bu_runner.py` — reading the job as JSON on
stdin. No package install in the bu venv, no `PYTHONPATH` gymnastics.

**2. Delete `settle`, don't relocate it.** `settle` (an `asyncio.sleep` wrapper)
is used *only* by the act-ladder we're deleting. Nothing else calls it. Relocating
it to a util module is carrying a corpse. **Leaner:** keep only `error_detail`
(the pipeline uses it) — inline it into the pipeline or a 10-line util; delete
`settle` and the rest of `engine.py` outright.

**3. Don't relocate `_is_listing`/`_match_restaurant` — keep a stub `ontopo.py`.**
`resolve.py` imports those two from `ontopo`. Relocating them + rewriting the
import is churn for zero gain. **Leaner:** strip `ontopo.py` down to just those
two helpers (delete `book_table` and the rest); `resolve.py`'s import keeps
working unchanged. Least diff.

**4. Defer recording retention (open Q1) — don't build pruning.** A
`bu_record_dir` that grows is a problem for *later*, at volume. v1 writes runs to
a dir, full stop. Pruning/retention is speculative; YAGNI. (Mark it with a
`ponytail:` note, don't code it.)

**5. Trim the result JSON.** `{success, stage, card_required, message}` is
enough for the persona to report. `details` is a catch-all — drop it until a
caller needs a field that isn't already in the four.

**6. No warm subprocess pool, no service.** A booking is seconds; a per-call
subprocess cold-start (~2–3 s) is noise. Don't build pooling/reuse "for latency"
— measure first; it won't be the bottleneck (the browser + LLM steps dominate).

**Not over-built (correct, don't touch):** the two-venv split — it is *forced* by
`browser-use` pinning `google-genai==1.65` against our `2.8`, not a choice. The
honest note: if browser-use ever unpins google-genai, collapse to one venv and
delete the subprocess boundary. The safety gate living in the prompt + `max_steps`
(agent literally never reaches the card-entry/confirm action) is the right place —
no separate guard layer needed for the dry-run.

**Verdict:** ship the spine. Apply: (1) plain-script runner not `-m`, (2) delete
`settle`+engine, keep only `error_detail`, (3) stub `ontopo.py` instead of
relocating, (4) no retention/pruning, (5) 4-field result, (6) no pool. Net: the
migration is mostly *deletion* (engine/agent/book_table) plus one small runner,
one small subprocess wrapper, and a one-line pipeline change. That is the lazy,
correct shape — the risk is over-cleaning neighbors, so keep the diff surgical.
