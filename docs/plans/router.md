# ROUTER layer — plan

> The router is the part of "the cradle" that turns *intent* into *which path runs*.
> It sits between Gemini (understanding) and the engine (doing). Today `pipeline.py` is
> hard-wired to restaurants: the Gemini `_SCHEMA` only has restaurant fields, and
> `run_booking` calls `resolve_ontopo_url` + `book_table` directly.
>
> **What "routing" means while there is exactly one flow:** tell "this is a restaurant"
> from "this is something else", run today's exact Ontopo path for the former, and reply
> honestly for the latter. That's the whole router for a one-flow system. The registry,
> the `Playbook` contract, and the generalized per-task detector are **deferred** — they
> must grow *out of* the 2nd real playbook (movie/insurance), which is blocked on recon
> sessions with Alon that haven't happened. Building them now means guessing the contract
> from a sample size of one and redesigning it at first recon. See the ponytail review at
> the bottom for the full rationale.

---

## Goal

From the Gemini turn, decide whether this is the one flow we can actually run (restaurant →
Ontopo) or not. If yes, run today's resolve+book path unchanged. If no, reply honestly in
persona ("not something I auto-close yet"). The *general* "classify → detect → pick playbook →
collect inputs → run-or-fall-back" machine is the shape this grows into once there's a 2nd
concrete flow to factor over — it is **not** built now.

Safety stays first-class even in the thin version: when the restaurant resolver is **ambiguous**
(`many`), we ask the user — the same verify-before-commit rule the booking path already follows.
The cuts below are about over-engineering, never about loosening a safety gate.

---

## Scope — NOW (the minimum that works)

One new thing, **no new files**, ~15 lines in `pipeline.py`. This is the entire shippable router
for a one-flow system.

### 1. Add `task_type` to the Gemini turn we already make

`pipeline.converse()` already does one structured Gemini call per turn and returns a dict. Add
**one field** to `_SCHEMA` and **one line** to `_EXTRACT`. Enum is `["restaurant", "other"]` only —
the buckets we can actually serve today. (`movie`/`insurance` join the enum *in the PR that adds
their playbook*; classifying into buckets with no behavior is shipping a label, not a feature.)

```python
# pipeline.py — add to _SCHEMA["properties"]:
"task_type": {"type": "string", "enum": ["restaurant", "other"]},
# leave "required" as ["reply", "ready"] — task_type defaults to restaurant when absent (below),
# so we don't force the model to emit it on every chit-chat turn.

# pipeline.py — append to _EXTRACT:
"שדה 'task_type': 'restaurant' אם זו הזמנת מסעדה, אחרת 'other'. "
"ברירת מחדל restaurant אם לא ברור עדיין."
```

No separate classifier call: we already pay for one Gemini turn per message and it already extracts
fields, so the label rides along for free. (`stagehand-best-practices.md` §3 — drive cheap work on
the model you're already calling.)

### 2. A thin switch in `run_booking` — restaurant runs today's path; everything else is an honest stub

`run_booking` gains a 4-line guard at the top. If `task_type` is anything but `restaurant`, set the
booking ground-truth to a `failed`/honest state, send the stub reply, and return. Otherwise fall
through to **today's exact `resolve_ontopo_url` → `book_table` body, byte-for-byte unchanged.**

```python
# pipeline.py — run_booking, right after the notify() def and `name = ...`:
task_type = fields.get("task_type") or "restaurant"
if task_type != "restaurant":
    _booking[phone] = {"state": "failed", "info": "לא נתמך עדיין"}
    await send_text(phone, "זה לא משהו שאני סוגר אוטומטית עדיין, אבל אני פה.")
    return
# --- from here down: the current resolve_ontopo_url(name) → book_table(...) body, unchanged ---
```

That reuses the existing `_booking` ground-truth + `_truth_note` mechanism (the `failed` state
already feeds "never fake status"), the existing `notify`/timeout wrapper, and the existing `none`/
`many`/`one` handling inside the restaurant branch. The `many` → "ask which one" path stays exactly
as it is — the safety gate is untouched.

> Why route in `run_booking` and not in `converse`/`handle_inbound`: `ready` only fires when the
> user has confirmed they want to act, and `run_booking` is the single place an action is launched.
> Putting the one branch there keeps the seam in one spot and leaves the chat loop alone.

### What NOW touches

Changed:
- `app/pipeline.py` — `_SCHEMA` (+`task_type` with `["restaurant","other"]`); `_EXTRACT` (+one
  task_type line); `run_booking` (+4-line guard above its current body). **~15 lines net, no new
  files.**

Not changed (NOW):
- `app/automation/engine.py`, `app/automation/ontopo.py` (`book_table`), `app/automation/resolve.py`
  (called exactly as today, return shape `{status, url, candidates}` unchanged — no `target`/`label`
  rename), `app/llm/intent.py` (persona), `app/db/memory.py`, `app/config.py`, `app/whatsapp/*`.
- The hard "ready=true only when you have all four" rule in `_EXTRACT` **stays** — it's the
  restaurant gate and there's no second flow to gate differently yet.

Tests:
- One case in the existing pipeline test (or a small new `tests/test_router_switch.py`): with
  `task_type="other"`, `run_booking` sends the honest stub and never calls `resolve`/`book_table`
  (assert via a fake/patched `resolve_ontopo_url`); with `task_type="restaurant"` (or absent), it
  takes today's path. No network. Mirrors `tests/test_resolve.py` style.

### Build steps (NOW)

1. **`pipeline.py`** — add `task_type` to `_SCHEMA` (`["restaurant","other"]`); append the one
   `_EXTRACT` line; add the 4-line guard at the top of `run_booking` over today's unchanged body.
2. **Test** — assert `other` → stub (no resolve/book call); `restaurant`/absent → today's path.
3. **Regression gate** — DRY_RUN on Hudson/Taizu still reaches the confirm screen exactly as before.
   The restaurant flow must be byte-for-byte the same behavior.
4. **`ruff check . && ruff format --check . && pytest`** — quality gate (per CLAUDE.md).

---

## Deferred (grows from the 2nd real flow)

None of the following is built now. Each is structure justified by the **2nd and 3rd** playbooks
(movie/insurance), which are explicitly blocked on recon sessions with Alon that haven't happened.
The plan's own success criterion — "the router/pipeline don't change when movie/insurance land" —
**cannot be validated with one example**, so the right move is to let these emerge *from* the PR
that introduces the 2nd concrete playbook, when there are two real shapes to factor over. Until
then they'd be a guessed contract you redesign at first recon. (See ponytail findings #1–#7.)

- **The `Playbook` / `InputField` / `SiteMatch` dataclass contract + `playbooks/` package.** Extract
  it **in the same PR as the 2nd playbook**, when the movie/insurance DOM (seat maps, login/Context,
  multi-page forms) reveals what the contract actually needs. One implementation defined before the
  second's shape is known is premature abstraction. (finding #1)
- **`router.py` as a module + the registry.** Defer the registry dict entirely. When it arrives,
  make it `dict[str, Playbook]` (single value, **not** a list) — a per-task ordered list with a
  try-each-detector / `pending_many` loop is dead code while every task type has exactly one site.
  The value becomes a list only when a task type genuinely gets a 2nd site. (findings #3, #6)
- **The `Route` tagged-union (`go`/`need`/`ask_site`/`agent`) + its constructors.** The pipeline
  already speaks `working | done | failed | none | ambiguous` via `_booking`, and `run_booking`
  already branches on `none`/`many`/success. Reuse that vocabulary; the only genuinely new state is
  "no playbook for this task_type", which is the one `if task_type != "restaurant"` check NOW already
  does. A parallel `Route` vocabulary plus a translation layer back to `_booking` is two state
  machines for one flow. When a 2nd flow lands, let `select()` return what `run_booking` already
  consumes. (finding #2)
- **The generalized per-task `detect` abstraction.** Today `resolve_ontopo_url` *is* the restaurant
  detector and `run_booking` reads its `{status, url, candidates}` directly. Keep it that way. The
  generalized `detect(fields) -> SiteMatch` contract — and the `url`→`target` / `+label` reshape —
  exists only to satisfy the deferred typedef; it's work created by the abstraction, not the task.
  Extract when the 2nd site forces a second detector. (findings #6, #7)
- **`gemini_field_keys()` / union-schema generation.** The restaurant fields
  (`restaurant/date/time/party_size/name/email`) are already in `_SCHEMA` by hand. Auto-merging a
  registry into the schema at import produces exactly the schema that's already there — pure
  indirection, and exactly the "plugin discovery framework" the non-goals warn against. When you add
  `movie_title`, add it to `_SCHEMA` by hand (one line; you're editing `pipeline.py` for that
  playbook anyway). Extract a generator only if hand-maintenance gets unwieldy at 3+ task types.
  (finding #3)
- **`InputField.binding` flag + per-field binding metadata.** The only flow today (restaurant) is
  `binding=False` on every field, and the verify-before-commit gate already lives in `book_table`'s
  `dry_run=True`. `binding=True` first matters for insurance (blocked). When it lands, decide whether
  to enforce at the runner (like `dry_run`) or as per-field metadata — don't pre-commit the
  mechanism. **Hard rule that survives regardless: the router/playbook never auto-submits a binding
  step.** (finding #5)
- **`movie`/`insurance` in the `task_type` enum.** Add each label to the enum (and its `_EXTRACT`
  instruction) in the PR that adds its playbook — same one-field change, but you're not classifying
  into buckets you can't serve. (finding #4)
- **Per-playbook input gating (replacing the hard "all four" `ready` rule).** The per-flow
  `_missing_required` gating is only meaningful once a 2nd flow needs *different* fields. Until then
  the restaurant "all four" rule in `_EXTRACT` is the gate. Extract when the 2nd playbook brings its
  own `input_schema`. (finding #2, §4 of the original design)

> The shared rule for everything above: **extract when the 2nd site forces it**, not before. A new
> task type should land as roughly "a new file + one registry entry" — but that contract is only
> trustworthy if it was *derived from* two concrete flows, so it's built with the 2nd, not ahead of
> it.

---

## Open questions / info needed from Alon

These block building the *movie* and *insurance* playbooks (not the router skeleton + restaurant
re-slotting, which I can build now against existing code).

1. **Movie — which chains, and one recon session each.** I need to script `detect` (which chain
   screens a film) + a `run` per chain. Please confirm the target chains and, for each, do one recon
   pass with me on the live site so I can capture the booking widget's real DOM/steps:
   - **Yes Planet / Rav-Hen** (same group?), **Cinema City**, **Lev Cinema**, **Hot Cinema** — which
     of these are in scope for v1, and which is the priority to script first?
   - Do these require **login** to *reserve seats* (vs only to pay)? This decides whether the router
     needs a per-site Browserbase Context now or can defer it.
   - Is seat selection in scope, or just "a ticket for movie X at time Y"? (Seat-map widgets are the
     hard part — affects whether this stays deterministic or needs the agent.)
   - A **test account** per chain (or your willingness to be in the loop for OTP) for a real run.

2. **Insurance — which comparison site, exactly one to start.** "A comparison site" is ambiguous and
   each is a different flow. Please name the **one** site for v1 (e.g. the specific portal) so I scope
   `detect`/`run` to it. Then I need from you:
   - A **recon session** on that site to map the form steps (it's a long multi-page form — this is
     where `input_schema` gets big).
   - Exactly **which inputs** it demands (ID number, license seniority, car details, etc.) — this
     becomes the `input_schema`, i.e. the "collect once" list Gever asks for.
   - Confirmation of the **binding step** (where it submits / takes payment) so I mark those
     `InputField`s `binding=True` and the runner stops at `dry_run` before it — same
     verify-before-commit gate the restaurant flow has. **Hard rule: the router/playbook never
     auto-submits a binding step.**
   - A **test identity** (or you in the loop) — I won't run a binding insurance step on your real
     details without explicit confirmation.

3. **Restaurant beyond Ontopo — do we care yet?** Is any target restaurant *not* on Ontopo (Tabit,
   etc.)? If "Ontopo-only for now" is fine, the restaurant task type stays a one-element list and I
   don't build a second restaurant detector. (My assumption: Ontopo-only for v1.)

4. **`task_type` enum — final list.** I'm proposing `restaurant | movie | insurance | other`.
   Confirm, or name anything else you want classified now so Gemini learns it from the first turn
   (cheap to add a label, expensive to retrain habits later).

5. **Agent fallback behavior for v1.** Confirm it's fine that `other`/no-site routes to an **honest
   persona reply** ("not something I auto-close yet") rather than a live Stagehand `execute` run. The
   real autonomous agent is the AGENT layer (separate plan); the router only *decides* it's an agent
   job. (My assumption: yes, stub for now.)

> Build steps for NOW live under "## Scope — NOW". The deferred multi-file build sequence
> (base.py → restaurant_ontopo.py → router.py → Route switch wiring) is intentionally gone:
> those files are the abstraction being deferred until the 2nd playbook — see "## Deferred".

---

## Ponytail review (over-engineering)

I have what I need. The plan is well-written and genuinely lazy in spirit (it keeps `book_table`, `act_verified`, `resolve.py` internals untouched), but for a codebase that today has exactly **one** flow and where movie/insurance are blocked on recon sessions that haven't happened, several pieces are built for a future that isn't here yet. Here are my findings.

---

## PRIORITIZED FINDINGS

**1. The whole `Playbook` dataclass contract + `playbooks/` package is a one-implementation abstraction. [highest]**
- *Why over-built:* You have exactly one playbook (restaurant/ontopo) and the other two are explicitly **blocked on recon sessions with Alon that haven't happened**. An interface with one implementation, defined before the second implementation's shape is known, is the textbook premature-abstraction trap — you're guessing the contract (`detect`/`run`/`input_schema`/`label`) from a sample size of one. When the movie playbook's real DOM lands, the contract will almost certainly need to change (seat maps, login/Context, multi-page forms), so you'll redesign it anyway.
- *Leaner:* Don't create `playbooks/base.py` or `playbooks/restaurant_ontopo.py` yet. Keep the restaurant path as-is. Build the dataclass contract **in the same PR as the second playbook**, when you have two real shapes to factor over. The plan even states the design's own test is "the router and pipeline don't change when movie/insurance land" — you can't validate that with zero second examples, so building it now is faith, not engineering.

**2. `Route` dataclass with 4 kinds + 4 constructors reinvents the `_booking` state machine you already have. [high]**
- *Why over-built:* `pipeline._booking` already speaks `working | done | failed | none | ambiguous`, and `run_booking` already branches on `none`/`many`/success. `Route` introduces a *parallel* vocabulary (`go | need | ask_site | agent`) that the plan then immediately maps back onto the existing `_booking` states in §6. Two state vocabularies for one flow, plus a translation layer between them.
- *Leaner:* `select()` can return what `run_booking` already consumes — a `(status, ...)` tuple or just reuse the `{"status": "one"|"many"|"none"}` dict that `resolve_ontopo_url` *already returns*. The only genuinely new state is "no playbook for this task_type" → that's one `if task_type not in registry` check, not a new tagged-union type.

**3. `gemini_field_keys()` / union-schema generation is speculative machinery for fields that don't exist. [high]**
- *Why over-built:* This generates JSON-schema props from the union of all playbooks' input fields "so adding a playbook auto-extends Gemini." There is only one playbook and its fields (`restaurant/date/time/party_size/name/email`) are **already hard-coded in `_SCHEMA`**. So this function, today, produces exactly the schema that's already there — pure indirection with zero payload. The plan even pre-writes a fallback (`details: object`) for when the union "proves noisy," which is a tell that the author already suspects it's the wrong call.
- *Leaner:* Cut it entirely. When you add `movie_title`, add it to `_SCHEMA` by hand — it's one line, and you're editing `pipeline.py` for that playbook anyway. Auto-merging a registry into a schema at import time is exactly the "plugin discovery framework" the non-goals say to avoid.

**4. `task_type` enum carrying `movie | insurance` Gemini can't act on yet. [medium]**
- *Why over-built:* Teaching Gemini to classify `movie`/`insurance` now, when both route to the honest-stub reply, means you ship a classifier for labels with no behavior. It also adds a `_EXTRACT` instruction block and makes `task_type` required on every turn.
- *Leaner:* Add `task_type` with enum `["restaurant", "other"]` only. `other` → honest stub. Add `movie`/`insurance` to the enum *in the PR that adds their playbook*. Same one-field, one-instruction change, but you're not classifying into buckets you can't serve.

**5. `InputField.binding` flag is config for a value that's `False` everywhere it exists. [medium]**
- *Why over-built:* The only playbook today (restaurant) has `binding=False` on every field (the plan says so explicitly). `binding=True` only matters for the insurance flow, which is blocked. So it's a field that's always `False` until a flow that doesn't exist yet.
- *Leaner:* Drop `binding` from the dataclass now. It arrives with insurance — and honestly the verify-before-commit gate already lives in `book_table`'s `dry_run=True`, so when insurance lands you may enforce it at the runner, not as per-field metadata. Don't pre-commit the mechanism.

**6. `detect` returning ordered candidate-list-per-task-type with first-`one`-wins loop. [medium]**
- *Why over-built:* `_REGISTRY` maps task_type → *list* of playbooks with an ordered try-each-detector loop and `pending_many` bookkeeping, for a world where every task type has exactly one element. That loop is dead code today.
- *Leaner:* `_REGISTRY: dict[str, Playbook]` (single, not list). `select` = look up one playbook, call its detect, branch. When a task type genuinely gets a second site, *then* make that value a list. Same one-line registry edit; no speculative loop.

**7. `restaurant_ontopo.detect` reshaping `resolve_ontopo_url`'s return (`url`→`target`, add `label`/`candidates`). [low]**
- *Why over-built:* `resolve_ontopo_url` already returns `{status, url, candidates}` and `run_booking` already reads `found["url"]` / `found["candidates"]`. The rename to `target` + `label` exists only to satisfy the generalized `SiteMatch` typedef — i.e. work created by finding #1, not by the task.
- *Leaner:* If you drop the `Playbook`/`SiteMatch` abstraction (#1), this adapter disappears — `select` calls `resolve_ontopo_url` directly and returns its dict unchanged.

---

## VERDICT

**Genuinely essential right now:** one new thing — a `task_type` field (`["restaurant","other"]`) on `_SCHEMA` so the pipeline can tell "not a restaurant" from "restaurant," and a 4-line branch in `run_booking`: if `task_type != "restaurant"`, set `_booking` to a failed/honest state and send the stub reply; otherwise run today's exact resolve+book path. That is the entire shippable router for a one-flow system, and it's ~15 lines in `pipeline.py` with **no new files**. **Cut for now:** the `playbooks/` package, `base.py`, the `Playbook`/`InputField`/`SiteMatch`/`Route` dataclasses, `router.py` as a module, `gemini_field_keys()` union-schema, the `binding` flag, the list-valued registry with its try-each loop, and the `detect`/`run` adapters — every one of these is structure justified by the *second and third* playbooks, which are explicitly blocked on recon that hasn't happened. The plan's own success criterion ("router/pipeline don't change when movie/insurance land") cannot be validated with one example, so building the abstraction now is betting the contract on a guess. **Riskiest over-build to watch:** the `Playbook` contract itself (finding #1) — if you build it before the movie flow's real DOM/login/seat-map constraints are known, you will redesign it the moment recon happens, having paid for the abstraction twice. The right move is to grow the abstraction *out of* the second playbook, not ahead of it: ship the `task_type` switch now, and let the registry/contract appear in the PR where you finally have two concrete flows to factor over.
