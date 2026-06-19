# Plan — the AGENT (fallback) layer

> Layer 5 of "the cradle". Stagehand's autonomous agent (`session.execute`) used **only as a
> fallback**, never on the hot path. Grounded in our installed `stagehand==3.21.0` (introspected,
> not guessed) and `docs/research/stagehand-best-practices.md`. Ponytail: one ~40-line coroutine
> (`run_agent_step`) wrapping `session.execute` as the **deepest rung of the existing
> `engine.act_verified` ladder** — when act_verified runs out of escalations on one step, the agent
> heals that one sub-goal, then the deterministic playbook resumes. No plugin framework, no registry,
> no second safety lock.

## Goal

Give the deterministic ladder a last rung: when `engine.act_verified` exhausts its escalations on a
**single step**, hand *that one sub-goal* to the Stagehand agent (`session.execute`), verify the
business state semantically via the caller's `ok(state)` check, and return control to the
deterministic playbook for the rest. The agent self-heals one stuck step — it never takes over the
booking, and it never reaches the human-confirmed commit step.

Why fallback and not default — the real numbers, stated plainly so we don't drift:

- **Cost.** The agent runs a multi-step LLM planning loop: every step is an extra model round-trip
  plus tokens, and it needs a stronger driver than our cheap per-step Flash. Industry-reported agent
  runs land around **~2–3x the token/$ cost** of a scripted deterministic flow for the same task.
  Our deterministic playbook is one grounded `act` per control; the agent re-plans the whole page on
  every step.
- **Reliability under faults.** The agent's long loop is exactly where transient network / 5xx /
  timeout faults compound and re-plan from a now-inconsistent page. It **collapses under faults**
  worse than a single `act_verified` step. So the agent runs only when deterministic has nothing.
- **Stagehand's own guidance** (research doc §1): *"Use agent for exploration, individual primitives
  for critical paths."* Booking is a critical path → deterministic-first, agent only when there's no
  playbook.

---

## Scope — NOW (the minimum that works)

**One new coroutine, `run_agent_step`, in `app/automation/agent.py` (~40 lines).** It is the
**deepest rung of the existing `engine.act_verified` ladder**: when act_verified exhausts its
escalations on a single step, it hands *that one sub-goal* to the Stagehand agent via
`session.execute`, then verifies the business state **semantically** through the caller's `ok(state)`
check and returns control to the deterministic playbook for the rest. It integrates with the
already-built engine and strengthens the shipping Ontopo flow — `act_verified` already returns
`False` on the party-size step (ontopo.py:171), so this is a **live wire today**, unlike unknown-site
which needs a router/site-detection that does not exist yet.

### The verified Stagehand agent API (our SDK, introspected)

`AsyncSession` exposes `execute` (and `act`/`observe`/`extract`/`navigate`/`end`). **There is no
`session.agent(...)` and no `session.replay()` on this SDK** — the research doc's `replay()` claim is
wrong for 3.21.0 (verified: `AttributeError`). For the NOW build we use one `execute` call with the
`dom` defaults hardcoded inline — no `mode`/`frame_id`/`should_cache` knobs:

```python
resp = await session.execute(
    agent_config={
        "mode": "dom",                                   # hardcoded; hybrid/cua deferred
        "model": {"model_name": settings.model_name},    # reuse the existing driver, no new knob
    },
    execute_options={
        "instruction": sub_goal,                         # the ONE stuck sub-goal, e.g. "בחר N סועדים"
        "max_steps": AGENT_MAX_STEPS,                    # the one budget knob (6)
        "use_search": False,                             # no web-search detours mid-booking
    },
    timeout=...,                                         # per-call HTTP timeout (httpx)
)
```

**Response shape (verified `SessionExecuteResponse`):**

```
resp.success: bool
resp.data.result:
    success: bool          # the agent's self-report — NOT proof the task completed
    completed: bool
    message: str
    actions: List[DataResultAction]
    usage: { input_tokens, output_tokens, cached_input_tokens, reasoning_tokens,
             inference_time_ms } | None   # cost accounting lives here
```

### Public interface

```python
# app/automation/agent.py

AGENT_MAX_STEPS = 6   # HARD step cap for one stuck sub-goal — the one budget knob


async def run_agent_step(
    session,
    sub_goal: str,                   # the ONE stuck step's goal, hardcoded by the caller (e.g. "בחר N סועדים")
    ok: Callable[[dict], Any],       # semantic verify — same contract act_verified already uses
    *,
    trace: list | None = None,
) -> tuple[bool, dict]:
    """
    The deepest rung of act_verified's ladder. When act_verified runs out of escalations on ONE
    step, hand that single `sub_goal` to the Stagehand agent via session.execute, then verify the
    *business state* via the engine's existing `extract` + the caller's `ok(state)` — we do NOT
    trust `data.result.success` as proof. Logs `usage`, appends to `trace`, and returns
    `(ok_passed, state)` so the deterministic playbook resumes for the rest of the booking. The
    agent only ever heals this one step; it never reaches the human-confirmed commit step.
    """
```

### The safety lock — STRUCTURAL only (non-negotiable)

The agent must **never** click a payment / submit / binding control. There is exactly **one** real
lock, and it is structural — not a keyword scan:

**The agent is only ever handed one mid-flow sub-goal, never the commit step.** `run_agent_step`
takes a `sub_goal` the caller **hardcodes** (e.g. the party-size step `"בחר N סועדים"`), and the
deterministic playbook simply never calls it for the binding step. The actual submit stays where it
already is: deterministic `session.act("confirm…")` in the playbook, reached **only** after
`dry_run=False` and a real user "yes" in WhatsApp. The agent heals a stuck mid-flow control; a
human-confirmed deterministic line commits the booking. Same shape as ontopo today — the
deterministic, human-confirmed submit already lives in `ontopo`.

Because the caller passes a **hardcoded** goal, there is no untrusted free-form goal to guard
against — so we add **no** `_is_binding` / `_BINDING` substring matcher: a fuzzy keyword scan
(`"pay" in "display"`) gives false confidence and the real button labels are unknown anyway (Q5).
The structural "agent never gets the commit step" gate is the whole defense.

What could go wrong with money, and how the structural gate stops it:

| Failure | Without gate | With structural gate |
|---|---|---|
| Agent "helpfully" clicks **Pay now** while healing a mid-flow step | real charge | the agent is never handed the commit step; submit is a separate human-confirmed deterministic line in ontopo |
| Agent loops and re-submits a half-filled order | duplicate binding action | the agent only heals one mid-flow sub-goal; the one real submit happens once, deterministically, after user confirm |
| Prompt-injection mid-step tells the agent to "complete purchase" | agent obeys | the agent's goal is a hardcoded mid-flow control, not the commit; structural no-commit-step gate holds |

This mirrors the existing `dry_run` gate and CLAUDE.md's hard line: **never auto-submit a
payment/binding step; always verify-before-commit; the user confirms.**

### Verification stays SEMANTIC

`run_agent_step` reuses the engine's existing `extract` helper + the caller's `ok(state)` contract
(the same one `act_verified` uses) for ground truth. The agent finishing the *action* is **not**
proof the *business state* moved — only `ok(state)` knows that. **We never treat
`data.result.success` as proof the step completed.** `ok` is the verdict: if it returns false, the
step is a failure regardless of what the agent self-reports, and the deterministic playbook surfaces
an honest failure rather than resuming on a false success.

### Guardrails (caps, cost, driver)

- **Step cap** = `AGENT_MAX_STEPS = 6`, the one budget knob — bounds the planning loop on one
  sub-goal (a single control needs far fewer steps than a whole site).
- **Wall-clock cap** = the agent runs *inside* the existing
  `asyncio.wait_for(..., BOOKING_TIMEOUT_S=240)` in `pipeline.run_booking`, plus the Browserbase
  session `timeout`. No new timeout machinery.
- **Cost accounting** = read `resp.data.result.usage` after the run, log it, append to `trace`.
  Confirms the ~2–3x assumption on our own traffic.
- **Driver model** = `settings.model_name` (the existing driver — currently `google/gemini-2.5-pro`,
  target `anthropic/claude-sonnet-4-6`). **No new `agent_model` knob** — it would equal the existing
  one. Mode is `"dom"`, hardcoded.
- **`use_search=False`** during any user-facing run.
- **Single attempt, not a loop.** Per stuck step, the agent is tried at most once. If it also fails,
  the deterministic playbook surfaces an honest Hebrew failure (existing pattern) — we do **not** keep
  paying for retries.

### How it fits the existing engine/code

- **`run_agent_step` is the deepest rung of `act_verified`'s ladder.** When act_verified exhausts its
  deterministic escalations on a step, it hands that one `sub_goal` to `run_agent_step` instead of
  returning `False` straight away. The agent heals the step; the playbook resumes. The ladder gains
  one rung, not a new parallel path.
- **The one live caller is the ontopo party-size step.** `act_verified` already returns `False` there
  (ontopo.py:171); `book_table` already has the `ok` lambda + read instruction/schema sitting three
  lines up (ontopo.py:174-176). The single `if not ok:` hook passes that same `ok` to
  `run_agent_step` — no new contract.
- **Same Browserbase session** the playbook already started (`self_heal=True`, Context for auth) —
  the agent heals in place, no second session, no re-login.
- **The deterministic playbook owns the flow.** `run_agent_step` returns `(ok_passed, state)` and
  control returns to ontopo for every remaining step — including the human-confirmed commit, which
  the agent is never handed.
- **Honest failure + trace + session_id** — same conventions as the engine.

### Files & changes (NOW)

| File | Change |
|---|---|
| `app/automation/agent.py` | **new.** `run_agent_step` + `AGENT_MAX_STEPS` + a `demo()` self-check with a fake session (mirrors `engine.demo`). **~40 lines.** |
| `app/automation/ontopo.py` | **one hook.** On the party-size step, where `act_verified` returns `False` (ontopo.py:171), add the `if not ok:` call to `run_agent_step`, passing the `ok` lambda + read instruction/schema already present (ontopo.py:174-176). |
| `tests/test_agent.py` | **new.** Fake-session tests: agent heals the sub-goal → returns `(True, state)`; `data.result.success=True` but `ok` returns false → returns `(False, state)` (semantic verify wins); `usage` is logged to `trace`. |
| `docs/plans/agent.md` | this file. |

No new config knob, no second safety lock, no registry, no plugin framework. One coroutine wrapping
`session.execute` + reuse of `engine.extract`/`ok` + the existing `(bool, state)` shape.

### Build steps (ordered — 2 steps)

1. **`agent.py`: `run_agent_step` + `AGENT_MAX_STEPS` + `demo()`** with a fake session (no network).
   Land the `execute` call shape (hardcoded `dom` + `model_name`), the semantic `ok` verify, and the
   `(ok_passed, state)` return. Prove in `demo()` that a `data.result.success=True` + failing `ok` is
   reported as `(False, …)` (mirrors how `engine.demo` self-checks offline).
2. **Wire the one ontopo hook + live drive.** Add the `if not ok:` call on the party-size step,
   passing the existing `ok` lambda; log `usage` to `trace`. Drive the real Ontopo flow against a
   page where the party-size step is flaky, confirm the agent heals it and the deterministic playbook
   resumes through to the human-confirmed commit.

---

## Deferred (grows later)

Built when there's a real trigger and the open questions are answered — not before:

- **Unknown-site end-to-end task (`run_agent_task`).** Drive a *whole* unknown site through
  `session.execute`, hard-stopped before the binding step, returning an `ActionResult` shaped like
  ontopo's `dry_run` result so the confirmation gate is reused. Defer until **the router can detect a
  non-restaurant site and hand the agent a concrete target** — its only caller (the router) does not
  exist yet, and it's blocked on Q1–Q6 (no Anthropic key, no target URL, no test account, no
  binding-button labels). When built, it takes a free-form task from the router; reintroduce a
  binding-label check *then* — with the real button labels from Q5, not guesses.
- **Recon → playbook authoring.** Point the agent at a new site, narrate the steps
  (`data.result.actions`), and emit a **draft playbook** a human reviews and freezes into
  deterministic code. Offline, never user-facing. Defer until there's a chosen target site, a test
  account, and the info from Q1–Q6 below. Humans freeze playbooks; the agent only drafts — never
  auto-generates deterministic code.
- **Separate `settings.agent_model` knob.** Add the day we actually run a different driver model for
  the agent loop than for the deterministic per-step path. Today they're the same value
  (`settings.model_name`), so a separate knob is flexibility for a state we're not in.
- **`mode="hybrid"`/`"cua"`, `frame_id`, `should_cache`.** Only if a real site defeats DOM grounding.
  CUA needs a coordinate-capable model + fixed viewport (research §4) — a deliberate per-site
  decision, not a default. Until then `mode="dom"` is hardcoded inline.
- **The router (Layer 1).** This plan's NOW build needs no router; the router brings its own
  site-detection + playbook dict, and is what unblocks `run_agent_task` above.

## Open questions / info needed from Alon

These need you to touch sites / pull info — please be concrete back:

1. **Anthropic key.** The agent loop wants `anthropic/claude-sonnet-4-6` (CLAUDE.md says "no
   Anthropic key yet — Gemini-only"). Do we have an Anthropic key now? If **no**, the NOW build runs
   on `settings.model_name` = `google/gemini-2.5-pro` (works, weaker planner, and CUA/hybrid would be
   off-limits). Confirm that's fine for the first unknown-site runs.

2. **First non-Ontopo target site(s).** Roadmap says cinema (all chains) + car-insurance comparison.
   Which **one** site do you want as the first unknown-site target? Please paste the exact URL of a
   cinema-chain booking page (e.g. a specific Yes Planet / Cinema City showtime page) **or** the
   insurance comparison site's start URL. I need a real deep-link, not a homepage.

3. **A test account + throwaway data.** For cinema/insurance the agent will hit login/OTP and a form.
   Please set up (and hand me):
   - a **test login** (or confirm guest checkout exists) for the chosen site;
   - a **disposable phone/email** for OTP that you can read codes from;
   - for insurance: **fake-but-valid-shaped** ID/car details to fill the form *up to* (never past)
     the binding step. **No real payment card** — the agent stops before payment by design.
   Without these, the agent can only map the public, pre-login part of the flow.

4. **When do I run the first unknown-site task?** Per the GeverAI Browserbase-reliability note, live
   iteration runs from this Mac. Confirm: I drive `run_agent_task` here, you watch the Browserbase
   live-view / replay, and we review the result together before any deterministic playbook is frozen.
   Is a 1-hour paired session workable, or do you want it unattended (I'd cap `max_steps` lower and
   you review the trace after)?

5. **The exact stop-before-commit label per site.** For the specific insurance/cinema site, what is
   the **exact label** on the final pay/submit button? I need the literal button text so the
   stop-before-commit *instruction* names the right control to halt before — this sharpens the
   advisory prompt; the structural lock (no agent call past commit) holds regardless.

6. **`mode` for the first site.** Default is `mode="dom"`. If you already know a target site is
   canvas/heavy-JS and DOM grounding won't see the controls, say so and I'll budget for `hybrid`/
   `cua` (needs the Anthropic/coordinate model from Q1 and a fixed viewport).


---

## Ponytail review (over-engineering)

I now have what I need. The plan reuses `act_verified`, `extract`, the `ok` contract, the `ActionResult` shape, the existing timeout, and the fake-session `demo()` pattern correctly. Here is the ponytail review.

---

## PRIORITIZED FINDINGS

**1. `run_recon` + `run_agent_task` are speculative — neither has a caller, and one needs info you don't have yet.**
The plan itself admits the router (the only caller of `run_agent_task`) does not exist, and recon is blocked on six open questions (no Anthropic key, no target URL, no test account, no binding-button labels). Building all three coroutines now is speculative-need. The only fallback shape with a real, today trigger is **(b) step recovery** — `act_verified` already returns `False` on the party-size step (ontopo.py:171), and that's a live wire. Cut `run_agent_task` and `run_recon` from this build entirely; ship **only `run_agent_step`** wired into the one flaky step. Add the other two when the router exists and Q1–Q6 are answered. This collapses the build from 6 ordered steps to ~2.

**2. Three separate step-cap constants for one knob that has one live use.** `AGENT_MAX_STEPS_TASK=14`, `_REPAIR=6`, `_RECON=25` is config for values that have no caller yet (task/recon are deferred per finding 1). Keep one: `AGENT_MAX_STEPS = 6` as the default arg to `run_agent_step`. The other two are pre-named budget knobs for code that doesn't exist.

**3. `settings.agent_model` is a new config knob for a value that equals the existing one.** Default is `anthropic/claude-sonnet-4-6` — **identical** to `settings.model_name` (config.py:13). The plan even admits it "falls back to `model_name` if you'd rather not." You'd rather not. A separate cheap-step-vs-agent-step model is real flexibility *for a state you're not in* (CLAUDE.md: Gemini-only, no Anthropic key). Use `settings.model_name` directly. Add the separate knob the day you actually run two different driver models — not before.

**4. `_BINDING` word-list + `_is_binding()` is a second lock guarding a door that lock #2 already welds shut.** The plan's own table shows the capability lock ("no agent call proceeds past `stop_before_commit`; submit is a separate deterministic human-gated `act`") stops every money failure on its own. `_is_binding` is a fuzzy substring match (`"pay" in "display"` → false positive waiting to happen; Q5 admits the real button labels are unknown). A best-effort keyword scan as your "airtight" lock is theater. For `run_agent_step` specifically — the only thing you're building — the caller passes a *hardcoded* goal (`"בחר N סועדים"`), so there's no untrusted binding goal to guard against. Cut `_BINDING`/`_is_binding` from this build. The structural gate (agent never gets the submit step; submit stays the deterministic human-confirmed line that already exists in ontopo.py) is the whole defense. Reintroduce a word-check only when `run_agent_task` takes a free-form task from the router — and then with the real button labels from Q5, not guesses.

**5. The `_PLAYBOOKS` dict placeholder is scaffolding for a layer you're deferring.** It belongs to the router (Layer 1), which this plan explicitly defers. A placeholder registry "so the seam is testable now" tests a seam nothing calls. Drop it; the router brings its own dict when it's built.

**6. `run_agent_step`'s parameter surface is wider than its one caller needs.** Signature carries `read_instruction`, `read_schema`, `ok`, `variables`, `trace`, `max_steps`. The single live caller (ontopo party-size) passes the *same* `ok` lambda and read instruction/schema already sitting three lines up in `book_table` (ontopo.py:174-176). Pass `ok` and reuse; `variables` is unused on the party-size step (no secrets). Trim to what step (b) actually hands it. Don't pre-build the full `act_verified`-parity surface for one call site.

**7. `mode`/`hybrid`/`cua` and `frame_id` in the documented call shape.** The plan already defers hybrid/cua ("only if a real site defeats DOM"). Good — but then don't thread `mode` as a configurable in the build; hardcode `"mode": "dom"` inline in the one `execute` call. A per-site mode decision with no second site is premature. Same for `frame_id`/`should_cache`/`use_search` — pass the dom default literally; don't surface them as knobs.

---

## VERDICT

**Genuinely essential:** one thin coroutine, `run_agent_step`, that wraps `session.execute(agent_config={...dom, model_name...}, execute_options={instruction=goal, max_steps=6, use_search=False})`, then verifies the *business state* via the existing `engine.extract` + the caller's `ok` lambda (never trusting `data.result.success`), logs `usage`, appends to `trace`, and returns `(bool, state)` — plus the one `if not ok:` hook on the ontopo party-size step, and a fake-session test mirroring `engine.demo`. That's the only piece with a real trigger today (`act_verified` already returns `False` there) and it correctly reuses everything that exists. **Cut to ship the minimum:** `run_agent_task`, `run_recon`, the `_PLAYBOOKS` placeholder, two of three step-cap constants, the `settings.agent_model` knob (use `model_name`), and the `_BINDING`/`_is_binding` lock (the structural gate is the real defense; the deterministic human-confirmed submit already lives in ontopo). This turns a ~150-line module + 6-step build into roughly a 40-line module + 2-step build. **The two riskiest over-build spots to watch if you do build more:** (a) treating `data.result.success` as proof of booking state — the plan says the right thing (verify semantically via `ok`), make sure the code actually does it and doesn't shortcut; (b) the `_is_binding` substring matcher giving false confidence — if it survives, it must never be described or relied on as the lock; the structural "no call past commit" gate is the only thing that actually holds.
