# Playbook layer — plan

## Goal

Eventually: a **per-site deterministic flowchart** abstraction so adding a site
(cinema, insurance) is "write a Playbook", not "write another 500-line `book_table`".

But you cannot factor a correct abstraction out of **one** instance. Today there is
exactly one real flow (Ontopo's `book_table`); cinema and insurance are still open
questions (which chain, deep-link or in-page seat flow, login/OTP, which insurance
site). The shape extracted from Ontopo *alone* is a guess.

So this plan does the lazy, build-ready thing: **extract nothing now.** It nails down
the *target sketch* of a Playbook and the *recon process* for authoring the SECOND
flow — because the abstraction must be **extracted from two real playbooks**, not
designed ahead of one. The second flow (cinema or insurance) is written as a plain
`book_*` function; when two real flows sit side by side, their duplication hands us the
exact, smaller abstraction — and *that's* when the `Playbook` dataclass + step-runner
get built (see Deferred).

Hard constraint, unchanged: **never auto-submit a binding step.** In today's
`book_table` the final `act("אשר את ההזמנה סופית")` is already structurally unreachable
while `dry_run=True` (the `if dry_run: return` returns first). That guarantee stays
exactly as-is — this plan touches no code that could weaken it.

---

## Scope — NOW (the minimum that works)

**Net code change to `ontopo.py`: none.** `book_table` stays exactly as it is today.
No lift into closures, no wrapper, no `playbook.py`. The Ontopo logic works; rewriting
it to serve a not-yet-existent abstraction is motion, not progress.

The only "now" deliverables are two documents — both authored in this file, no code:

### 1. Target sketch — the eventual `Playbook` shape

The shape we are aiming *at*, recorded so the second flow can be written with it in
mind (not built against it). When extracted, a Playbook is two things:

```
Playbook = {
    input_schema: <what the ROUTER must collect before running>
    steps:        <ordered (action, verify) pairs, each a step run through
                   engine.act_verified; the last data-changing step before
                   anything irreversible is a confirm gate (dry_run)>
}
```

That's the whole target. Notes that keep the eventual extraction honest:

- `input_schema` is the single source of truth for "what to ask" — its real first use
  is a test asserting field names match what `pipeline.run_booking` already passes. That
  test needs a **`list[str]` of names**, not a `Field` dataclass. Ontopo's set today:
  `restaurant, date, time, party_size, name, phone`.
- `steps` are **plain async closures**, each wrapping one `engine.act_verified` call
  directly. No `widget_step` factory (a 1:1 wrapper around an already-clean call only
  obscures — see Ponytail review #2). No agent-fallback seam (a config knob guarding a
  no-op stub is pure speculative flexibility — see Ponytail review #4).
- The confirm gate is **not a new mechanism** — it's the `if dry_run: notify+return`
  that already exists in `book_table`. Keep it structural: the binding `act` lives
  *after* the gate, so it stays unreachable in dry_run.

This sketch is a target, not a contract. Do not add fields nothing reads yet
(`match`, `task_type`, `Field.hint`) until the ROUTER actually reads them.

### 2. Recon recipe — how to author the SECOND flow

This is the concrete "now" work product: the repeatable process for standing up the
next real flow (cinema or insurance) as its **own plain `book_*` function**, modeled on
`book_table`. Two real flows is the precondition for extracting the abstraction.

- **(a) Recon — one observe-mode crawl.** Drive the live target once. For each logical
  action, call `observe(instruction=…, options={selector: <widget container>})` to
  capture the candidate (description / selector / method / backend_node_id) and an
  `extract` schema that reads the resulting state. Scope `observe` to the widget
  container so candidates don't fight page chrome (research doc §2/§6).
- **(b) Freeze.** Turn each captured `(observe instruction, extract schema, ok-predicate)`
  into a direct `engine.act_verified` call inside the new `book_*` function — exactly the
  pattern `book_table` uses today for party-size and date. Place the `if dry_run:` confirm
  gate **before** the first binding action, mirroring `book_table` lines 258–273. The
  `execute`/agent is allowed *here, in recon only*, to discover the step order — then it's
  thrown away; the frozen deterministic `act_verified` calls are what ship (doc §6 item 12,
  "`execute` recovers/discovers, never the hot path").
- **(c) Wire it.** Add the new `book_*` to `pipeline.run_booking`'s dispatch the same way
  Ontopo is wired today. No registry, no `match` predicate yet — a plain `if/elif` on the
  detected site is enough for flow #2.
- **(d) Verify.** One DRY_RUN to the gate; capture `details["trace"]` as that flow's
  baseline. Same loop as Ontopo (open question #1).

When flow #2 exists and passes, the duplication between `book_table` and `book_<flow2>`
is read directly — *that* diff defines the real `Playbook`/step-runner (Deferred below),
and it will be smaller and truer than anything designable from Ontopo alone.

### Files touched — NOW

- **`docs/plans/playbook.md`** (this file) — the target sketch + recon recipe above.
- **`ontopo.py`** — untouched.
- **`config.py`** — untouched (no `agent_fallback_enabled` flag; it'd guard nothing).
- No `app/automation/playbook.py`.

---

## Deferred (grows from the 2nd real flow)

Everything here is built **after** cinema/insurance recon yields a second concrete
`book_*` flow, extracted *from* the two real flows rather than designed ahead of them.
Listed so the eventual extraction is fast, not so it's built early.

- **The `Playbook` dataclass + registry.** `site`, `input_schema`, `steps`, and
  `start_kwargs` (per-site session knobs, research §4/§6). Registry stays a plain
  `dict[str, Playbook]` — no plugin framework, no entry-point discovery. Add `match` /
  `task_type` only when the ROUTER actually branches on them.
- **Lifting Ontopo's logic into step closures.** Once flow #2 shows which steps
  genuinely repeat, port `book_table`'s navigate / verify / party / date / availability /
  time / fill / gate / commit blocks into closures — *verbatim*, behavior-preserving —
  and likewise for flow #2. Until then, leave `book_table` inline; lifting it for its own
  sake is motion, not progress.
- **The step-runner.** A ~25-line `for step in pb.steps` loop returning the existing
  `ActionResult`, so `pipeline.run_booking` is unchanged downstream. Linear only — a list
  and a for-loop, because the flows are linear (navigate → fill → gate → commit). No state
  machine, no DAG, no branch primitive until a real site needs one (a step can `halt` /
  write `ctx.data` for a later step to read).
- **Step return shape.** Decide it from what the runner actually branches on across the
  *two* flows (continue / stop-with-message / commit). `act_verified` already returns
  `(success, state)`; don't model a five-field control vocabulary the linear flow doesn't
  use until two flows prove it's needed.
- **`input_schema` → ROUTER contract.** Promote field names to a richer schema (hint /
  required / default) only when the ROUTER reads them. The conversation layer
  (`pipeline._SCHEMA` / Gemini `_EXTRACT`) is rewired in the ROUTER task, not here.
- **Agent fallback.** A stuck step → autonomous-agent recovery (`session.execute`) is
  built in the AGENT task, where its real shape is known — not pre-seamed here with a
  dead `needs_agent` signal, an `escalate_to_agent` stub, and an off-by-default config
  flag. Today's behavior — stuck step → honest failure — is already what `book_table`
  does by doing nothing.

**Safety note (applies to every deferred item):** when the runner is eventually built,
the confirm gate stays the last data-changing step and the binding `act` stays
structurally after it — exactly as `book_table` enforces today. The cuts above are
over-engineering only; none touch the verify-before-commit / dry_run guarantee.

---

## Open questions / info needed from Alon

These are the things I can't get from the code — most need you to touch a site or pull a
value. Blocking items marked **[blocks]**.

1. **Ontopo regression baseline.** Even though I'm not refactoring Ontopo now, I want a
   known-good trace on file. Can you run one DRY_RUN booking (Hudson or Taizu, the two
   proven ones) and save/paste the resulting `details["trace"]`? It's the baseline every
   future flow (and any eventual extraction) diffs against. **[blocks regression sign-off
   for the eventual extraction, not any current coding.]**

2. **Cinema — which chain first, and is there a deep-link?** The *second* flow needs one
   concrete target. Which chain (Yes Planet / Cinema City / Lev / Rav-Hen)? And
   critically: does it have a stable per-movie/per-showtime **URL** the way Ontopo does
   (so the flow can `navigate` directly), or does seat selection only exist behind an
   in-page flow (search → pick movie → pick showtime → seat map)? This decides whether
   cinema is "Ontopo-shaped" or needs extra steps. Send me one example URL of a showtime
   page you'd want to book.

3. **Cinema login / OTP.** Do the chains require an account to hold seats? If yes, the
   research doc's Browserbase **Context (persist:true)** is needed per user — and I'll
   need a **test account** (username/login) for the recon. Do you have one, or should the
   first cinema flow target a chain that lets you reserve as a guest?

4. **Insurance — which comparison site, and the hard stop.** Which site (e.g. a specific
   Israeli מסלקה/comparison portal — name it)? Insurance is where the binding/payment step
   lives, so I want to confirm the rule with you in writing: **the flow stops at the
   quote/summary and `notify`s you; it never submits the purchase or enters card details
   autonomously.** Confirm that's the intended boundary for v1 (quote only, human
   commits). **[blocks insurance flow scope.]**

5. **Recon session budget.** Authoring a new flow = one **observe-mode crawl** (recon
   recipe step a): I drive the live site once in agent/observe mode to map
   steps+selectors, capture them, and freeze them into a plain `book_*`. That spends
   Browserbase minutes on the live site. OK to run 2-3 such recon sessions per new site
   against the real site? Any site I should *not* hit repeatedly (rate limits / they'll
   notice)?

6. **Test phone numbers / fake PII for recon.** For cinema/insurance recon I'll fill
   forms up to (not through) the binding step. Give me a phone + name you're OK using for
   these dry runs (not real card data — that never gets entered; per the research doc
   card/OTP go through `options.variables` only at real-commit time, which we're not doing
   in recon).

7. **Model for the driver.** Code defaults to `anthropic/claude-sonnet-4-6` but
   `CLAUDE.md` says we're Gemini-only today (no Anthropic key). The second flow will use
   whatever `book_table` uses now (`MODEL_NAME` / `google/gemini-2.5-pro`) so nothing
   changes — just confirm we're still Gemini-only so I don't accidentally wire a Sonnet
   path that 401s.

---

## Ponytail review (over-engineering)

I now have the full picture. The plan abstracts a single working 190-line function. Let me apply the ponytail ladder against the actual code.

## Ponytail review — PLAYBOOK layer plan

### Prioritized findings

**1. The whole "Playbook" abstraction exists to serve sites that don't exist yet · speculative need · keep `book_table` as-is until site #2 is real.**
The plan's own goal is "adding a new site is *write a Playbook*." But there is exactly one site (Ontopo), and the next two (cinema, insurance) are still a wall of open questions (#2–#6: which chain, deep-link or not, login/OTP, which insurance site, recon budget). You cannot factor a correct abstraction out of *one* instance — the shared shape you extract from Ontopo alone is a guess, and the open questions show cinema may not even be Ontopo-shaped (in-page seat flow vs. URL navigate). This is the textbook "build the framework before the second user." The lean move: **don't build `playbook.py` now.** When the cinema recon is done and you have a *second* concrete flow, the duplication between two `book_*` functions will tell you exactly what to extract — and it'll be a smaller, truer abstraction than this one. Everything below is conditional on building anyway.

**2. `widget_step` factory · a closure-builder that wraps a single `act_verified` call you already call cleanly inline · drop it; call `act_verified` directly inside step closures.**
Look at the real code: party-size and date are already two tidy `act_verified` calls. `widget_step` adds `callable_takes_inputs(ok)`, `action(ctx.inputs) if callable(action)`, a `writes` indirection, and a `goal`-derivation — machinery to turn 6 already-named keyword args into... 6 keyword args, plus a deferred-call layer so `action` can be either a value or a lambda. That's reinventing a function call. If steps are closures (they are), the closure body is just `await engine.act_verified(ctx.session, action=f"בחר {ctx.inputs['party_size']} סועדים", ...)` — strictly shorter and more readable than threading it through the factory. The "1:1 mapping" the plan brags about is the tell: when your wrapper is 1:1 with the thing it wraps, delete the wrapper.

**3. `StepResult` with five fields (`ok`/`state`/`halt`/`summary`/`needs_agent`) · models a control-flow vocabulary the linear flow doesn't have · collapse to what the runner branches on.**
The runner distinguishes: continue, stop-with-message, escalate. `act_verified` already returns `(success, state)`. `halt` vs `not ok` both return the same `ActionResult(success=False, ...)` in `run_playbook` — the distinction is cosmetic. `state` is carried but the runner only ever reads `summary`. `needs_agent` gates a stub that returns `failed` unchanged. So three of five fields drive nothing today. A step that returns `(success: bool, summary: str)` — or just raises a `Halt(summary)` for the early-exit cases — covers every branch the runner actually takes.

**4. `escalate_to_agent` seam + `needs_agent` signal + `agent_fallback_enabled` config · a flag and a stub for a feature in a different, unstarted task · delete all three; let a failed step fail.**
The plan is explicit: the function "is a stub returning `failed` unchanged," the flag "defaults OFF until the AGENT task lands," "behavior == today." So this is pure scaffolding for a future task — a config knob guarding a no-op, a signal field nothing consumes, and a named seam. Today's behavior is "stuck step → honest failure," which the plan preserves *by doing nothing*. Build the seam in the AGENT task, where you'll know its real shape. Config-for-a-value-that-never-changes-yet is exactly the smell. (`config.py` is the "single source for config" per CLAUDE.md — don't add dead knobs to it.)

**5. The `match`, `task_type`, and `Field` machinery for the ROUTER · contract for a layer the plan says it isn't building · don't add fields nothing reads.**
`Playbook.match` (ROUTER hook), `task_type`, and the `Field` dataclass with `required/hint/default` exist for a ROUTER that "this plan only *exposes* the schema." But `book_table` hardcodes `ONTOPO` and the Gemini prompt isn't rewired. So `match` is never called, `task_type` is never branched on, and `Field.hint` is never displayed. The schema-as-data has *one* real use this plan claims: a test asserting field names match `run_booking`'s kwargs. You don't need a `Field` dataclass for that — a `list[str]` of names (or even just the test reading the function signature) proves the same thing. Add `Field` when the ROUTER actually reads `hint`.

**6. `RunCtx` dataclass · a parameter bag for one call site · fine if it stays, but it's carrying dead weight.**
`RunCtx` is the least offensive piece (passing context to closures is reasonable), but note `trace`, `data`, and `dry_run` are the only fields the logic uses; `notify` and `session` are just the two args `book_table` already has. If findings 1–5 shrink this to one or two real steps inline, `RunCtx` dissolves into local variables. Watch it.

**7. `demo()` self-check (~120 lines, fake session, 3-step fake playbook) · a test of the abstraction living in the abstraction · if the abstraction shrinks, this evaporates.**
`engine.demo()` exists because the engine has real retry/escalation logic worth a no-network smoke test. A 25-line for-loop runner does not earn a 120-line fake-session harness proving "a list runs in order." The real regression guard the plan already names is better: same restaurant/date/party, diff the trace against baseline (open question #1). Keep that; skip `demo()`.

### Verdict

**Genuinely essential: almost none of this, *now*.** The hard constraint that actually matters — the confirm gate must be structurally unskippable while `dry_run=True` — is *already* enforced in today's code by the `if dry_run: return` before the final `act`, and it's already a clear, single-purpose block. The plan's one defensible idea is making `input_schema` explicit data so the future ROUTER has a contract, and even that is a `list[str]` plus a test, not a `Field` dataclass. **What to cut to ship the minimum:** don't write `playbook.py` at all yet — there's one site, the second is undefined, and you can't extract a true abstraction from N=1. Build the cinema flow as a *second plain `book_*` function*; when you have two real flows side by side, the duplication will hand you the exact (and far smaller) abstraction — no `widget_step` factory, no `StepResult` five-field protocol, no `escalate_to_agent`/`needs_agent`/`agent_fallback_enabled` dead-flag trio, no `match`/`task_type` ROUTER hooks. If Alon insists on landing the shape now for sequencing reasons, the two riskiest over-builds to watch are the **`widget_step` factory** (a 1:1 wrapper around a call that's already clean — it will only obscure) and the **agent-fallback scaffolding** (a config knob guarding a no-op stub, the purest speculative flexibility in the plan). The Ontopo logic itself is fine; resist the urge to "lift it into closures" for its own sake — that's motion, not progress, until a second site forces it.

Plan file reviewed: `/Users/alonb/Desktop/GeverAI/docs/plans/playbook.md`. Grounded against `/Users/alonb/Desktop/GeverAI/app/automation/ontopo.py` (the real `book_table`, lines 106–294) and `/Users/alonb/Desktop/GeverAI/app/automation/engine.py` (`act_verified`, lines 89–126).
