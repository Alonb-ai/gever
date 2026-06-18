# Stagehand + Browserbase best practices — for Gever's automation engine

Scope: improving `app/automation/engine.py`, `ontopo.py`, `resolve.py`, `pipeline.py`.
Target SDK: **Python `stagehand` v3.21.0** (the Stainless-generated, OpenAI-style client —
*not* the older `stagehand-py` v0.x with `Stagehand(...).page.act(...)`). Driver model today:
`google/gemini-2.5-pro`; planned: `anthropic/claude-sonnet-4-6`.

Every SDK claim below was verified by introspecting the installed package via
`.venv/bin/python -c "import inspect; ..."`. Doc claims are cited inline. **Where the
public docs (TypeScript-first) and our installed Python SDK disagree, it is called out
explicitly** — this matters a lot, because most of the web examples do not run as-is on our SDK.

---

## Top recommendations

1. **Fix `_clean_candidate` — keep `backend_node_id`, just drop `None` keys.** The HTTP 400
   is *not* caused by `backend_node_id` existing; it is caused by sending it as `null`. The
   SDK's `maybe_transform` passes `backend_node_id=None` straight through to the wire as
   `"backendNodeId": null`, and the server rejects `null` for a field typed `float`. The
   correct, typed replay is to pass the observe candidate with **None-valued keys removed but
   the real `backend_node_id` preserved when present** (it is the deterministic anchor — our
   current code throws it away). Concretely: `cand.model_dump(by_alias=False, exclude_none=True)`
   on the `DataResult`, or for our dict path just `{k: v for k, v in cand.items() if v is not None}`.
   Do **not** use the SDK's `.to_dict()` — it is buggy for this type (emits both `backendNodeId: null`
   *and* `backend_node_id: <value>`, a double key). (Verified empirically; see §1.)

2. **Detect "act succeeded but nothing changed" from the act response itself, before falling
   back to extract.** `act()` returns `data.result.{success, message, action_description, actions[]}`.
   A silent no-op typically shows up as an empty `actions` list or a `message` describing that
   nothing matched, even while top-level `success` is `true`. Check `len(result.actions) == 0`
   as a cheap first signal, then keep our extract-based ground-truth verification as the
   authoritative check. This catches the silent-failure class one LLM call earlier and cheaper. (§2)

3. **Turn on the SDK's own reliability knobs at `sessions.start`, which we currently leave at
   defaults: `self_heal=True`, `dom_settle_timeout_ms=…`, and `verbose=2`.** `self_heal`
   exists as a first-class start param and is exactly the "adapt when the DOM changes" behavior
   we are hand-rolling in `_attempt`'s escalation ladder. `dom_settle_timeout_ms` replaces our
   fixed `SETTLE_S = 1.2` sleep with an actual wait-for-DOM-settle that the engine performs
   *inside* each act/observe/extract — far better for Ontopo's custom widget. (§2, §4)

4. **Use `options.variables` for every sensitive field (card, OTP, ID number, password) in the
   insurance/cinema flows — never interpolate secrets into the `input` string.** Confirmed working
   on our Python SDK: `act(input="type %card% into the card field", options={"variables":
   {"card": {"value": "...", "description": "credit card"}}})`. The values are substituted
   server-side and are **not sent to the LLM provider**. Our current `ontopo.py` builds
   `f"מלא טלפון: {phone}"` — fine for a phone, unacceptable for card/OTP. (§3)

5. **Set per-call model override + per-call timeouts via `options`, and stop pinning the legacy
   `google/gemini-2.5-pro`.** `options.model` and `options.timeout` plumb through correctly on our
   SDK (verified). This lets us drive cheap/fast DOM steps with `google/gemini-2.5-flash` (the
   documented production default for act/observe/extract) and escalate *only the hard step* to
   `anthropic/claude-sonnet-4-6` — without changing the session. Note `google/gemini-2.5-pro` is
   **no longer in Stagehand's first-class act/observe/extract model list**; we are on a legacy
   string. (§3, §4)

6. **For login/OTP/payment, persist auth with a Browserbase Context (`browserSettings.context =
   {id, persist: true}`) and resume it on every run.** This is the single most important change for
   the insurance and cinema chains: it keeps cookies/localStorage/session across runs so we are not
   re-doing OTP every time. Wire it through `browserbase_session_create_params`. (§4)

7. **Replace the blanket `except Exception` with typed error classification.** The SDK exposes a
   clean hierarchy with `status_code`: `BadRequestError(400)`, `AuthenticationError(401)`,
   `PermissionDeniedError(403)`, `RateLimitError(429)`, `APITimeoutError`, `APIConnectionError`,
   `InternalServerError`, all under `APIError(StagehandError)`. Classify recoverable (429 / timeout /
   connection / 5xx → retry with backoff) vs fatal (400 / 401 / 403 → stop, surface honestly).
   Right now a 400 from a bad candidate and a 429 rate-limit are treated identically. (§5)

8. **Capture the session replay/live-view URL on every booking and put it in the failure trace.**
   `bb.sessions.debug(id)` → `debuggerUrl`, and `GET /v1/sessions/{id}/replays`. We already stash
   `session_id` in `details`; adding the replay URL makes every silent failure debuggable after the
   fact instead of guessing from the trace. (§4)

---

## 1. Primitives: act / observe / extract / agent, and the observe→act 400

### The four primitives (when to use each)

- **`act(input=...)`** — perform one atomic UI action. Docs are emphatic: *"Act instructions
  should be atomic and specific"* — ✅ "Click the sign in button", ❌ "Type in the search bar and
  hit enter" (multi-step). Our `ontopo.py` already follows this (one widget control per `act`),
  which is correct. ([act docs](https://docs.stagehand.dev/v3/basics/act),
  [repo claude.md](https://github.com/browserbase/stagehand/blob/main/claude.md))
- **`observe(instruction=...)`** — discover candidate actions (returns selectors+methods) and
  *plan* before acting. Use it to (a) check an element exists, (b) get a deterministic action object
  to replay. ([observe use case](https://docs.stagehand.dev/v3/best-practices/usecase-observe))
- **`extract(instruction=, schema=)`** — read typed data from the page. This is our verification
  workhorse and the right tool for it. ([best practices](https://docs.stagehand.dev/examples/best_practices))
- **`execute(agent_config=, execute_options=)`** — *this is the "agent" / autonomous mode in our
  Python SDK.* There is no `session.agent(...)` on `AsyncSession`; the generated SDK exposes
  `session.execute(...)` (verified). It runs a multi-step autonomous loop (`execute_options.instruction`,
  `max_steps`, `tool_timeout`, `use_search`) and supports a CUA/hybrid mode via
  `agent_config.mode ∈ {"dom","hybrid","cua"}`. Docs guidance: *"Use agent for exploration,
  individual primitives for critical paths."* For Gever's booking — a known, deterministic flow —
  **stay on act/observe/extract; do not use `execute` for the Ontopo happy path.** `execute` is
  attractive for the *discovery* phase of a brand-new cinema chain we have not scripted yet.
  ([browserbase blog](https://www.browserbase.com/blog/ai-web-agent-sdk),
  [computer-use docs](https://docs.stagehand.dev/v3/best-practices/computer-use))

### The observe-before-act pattern (the documented "right way")

Docs (TS) show:
```ts
const [action] = await stagehand.observe("click the login button");
if (action) await stagehand.act(action);   // pass the observe result object straight back
```
The point: `act` accepts **either a string or the action object returned by observe**, and replaying
the object reuses the exact selector/method, which is deterministic and dodges a second LLM grounding
pass. ([act docs](https://docs.stagehand.dev/v3/basics/act),
[observe use case](https://docs.stagehand.dev/v3/best-practices/usecase-observe))

In our **Python v3.21 SDK** this is typed precisely (verified by introspection):
- `act(input: Union[str, ActionParam])`. `ActionParam` is a `TypedDict` with **required**
  `description` + `selector`, and optional `arguments`, `method`, `backend_node_id` (aliased to
  `backendNodeId`, typed `float`).
- `observe()` returns `SessionObserveResponse` where `data.result: List[DataResult]`, and each
  `DataResult` has exactly those same fields (`backend_node_id: Optional[float]`).

So the *intended* deterministic replay is: `cand = observe_resp.data.result[0]; await session.act(input=cand)`
— pass the typed model (or its dict) straight through.

### Root cause of our HTTP 400 "Invalid input" (verified empirically)

Reproduced **without a network call** using the SDK's own transform:
```text
maybe_transform({'description':'d','selector':'s','method':'click','arguments':['x'],
                 'backend_node_id': None}, ActionParam)
  ->  {'description':'d','selector':'s','method':'click','arguments':['x'],'backendNodeId': None}
```
The SDK does **not** drop `None`; it serializes `backend_node_id=None` to `"backendNodeId": null` on
the wire. The server's schema types that field as `float`, so `null` → 400. **The trigger is the
`null`, not the key.** Our empirical "strip backend_node_id" fix works only because it happens to
remove the offending null — but it also throws away the *real* backend id on the (common) happy path
where observe *did* return one, degrading the replay to selector-only.

**Correct fix (keeps the determinism we paid an LLM call to get):**
```python
def _clean_candidate(c: dict) -> dict:
    # keep every field observe gave us, drop only None-valued keys (None -> null -> 400)
    return {k: v for k, v in c.items() if v is not None}
```
or, if working from the typed response object:
```python
cand = observe_resp.data.result[0]
await session.act(input=cand.model_dump(by_alias=False, exclude_none=True))
```
Both verified to produce a clean payload (`backend_node_id` preserved when present, omitted when
None). **Do not** use `cand.to_dict()` — for this model it emits *both* `backendNodeId: null` and
`backend_node_id: <value>` (a broken double-key), verified.

> Conflict to record: the public **caching** docs
> ([caching](https://docs.stagehand.dev/v3/best-practices/caching),
> [deterministic agent](https://docs.stagehand.dev/v3/best-practices/deterministic-agent)) describe a
> **`cacheDir` local-file cache** that records actions on first run and replays them with zero LLM
> tokens. **That parameter does not exist in our Python v3.21 SDK** (no `cacheDir` on `start` or
> anywhere — verified). In our SDK, deterministic replay is achieved two ways instead:
> (a) **manually** caching observe `DataResult` objects in our own code and re-feeding them to `act`
> (the pattern above — this is what we should do); and
> (b) **server-side** caching via `execute(..., should_cache=True)` plus the **`session.replay()`**
> endpoint, which returns the recorded action list (`SessionReplayResponse.data.pages[].actions[]`
> with method/parameters/result/token_usage). The `cacheDir` examples on the web are TS-only and will
> mislead — ignore them for our codebase.

---

## 2. Reliability best-practices

### Atomic actions — we already do this; keep it
One widget control per `act`. Good. The escalation ladder in `engine._attempt`
(blind act → observe→act → targeted instruction) is a sensible hand-rolled self-heal.

### Self-healing — stop hand-rolling all of it; turn on `self_heal`
`sessions.start(..., self_heal=True)` is a first-class param (verified). It is the SDK's built-in
"adapt when the action fails / DOM changed" behavior — overlapping with our manual escalation.
Recommendation: enable `self_heal=True` *and* keep our extract-verify loop on top (the SDK heals the
*action*; only our `ok(state)` check knows whether the *business state* actually changed). Don't
remove `act_verified` — it is doing something the SDK can't (semantic verification).

### Settling / waiting for the SPA — replace the fixed sleep
We use `SETTLE_S = 1.2` `asyncio.sleep` after every act. Two upgrades:
- **`sessions.start(..., dom_settle_timeout_ms=…)`** makes each act/observe/extract wait for the DOM
  to settle internally (verified param). This is the proper SPA wait and removes most of the need for
  a blanket sleep.
- **Per-call `options.timeout`** (ms) on the *act/observe/extract* call for slow widgets, e.g. the
  Ontopo time-slot grid that loads after date selection. Docs example:
  `act(..., options={"timeout": 10000})`. ([act docs](https://docs.stagehand.dev/v3/basics/act))
- Keep a *small* `settle()` only as a final safety net, not as the primary mechanism.

### Detecting "act succeeded but nothing changed" (our core problem)
Two layers, cheapest first:
1. **Inspect the act response.** `act()` → `SessionActResponse.data.result` has
   `success: bool`, `message: str`, `action_description: str`, `actions: List[...]` (verified
   fields). A silent no-op commonly returns an **empty `actions` list** and/or a `message` saying
   nothing was matched, even with top-level `success=true`. Treat `not result.actions` as a strong
   "nothing happened" signal and escalate immediately — before spending an extract call.
2. **Authoritative ground-truth via extract** — what `act_verified` already does, and the only
   thing that knows the widget's *semantic* state (party size actually = N, date actually = D). Keep it.

This two-layer check (response shape → semantic extract) is strictly better than today's
extract-only check, and catches the silent failure one step earlier.

### Retries / timeouts / idempotency
- **Transport-level retries are already built in**: the client has `DEFAULT_MAX_RETRIES` and retries
  429/5xx/connection errors with backoff automatically (Stainless client behavior). Our per-step
  `tries=3` loop is *application-level* retry (re-grounding the action) — different and complementary;
  keep it, but don't double-retry transport errors (classify first — see §5).
- **Idempotency** matters most at the irreversible confirm step. Our `dry_run` gate is the right
  shape. For the real booking, after `act("confirm")` always **verify via extract** (confirmation
  number) rather than re-clicking — re-clicking a confirm is the dangerous non-idempotent case.

---

## 3. Python SDK v3.21 types (the exact shapes)

All verified by introspection of the installed 3.21.0.

### `act`
```python
session.act(input=...)         # input: Union[str, ActionParam]
session.act(input=..., options={...}, frame_id="...")
```
- `ActionParam` (TypedDict): `description` (req), `selector` (req), `arguments: list[str]`,
  `method: str`, `backend_node_id: float` (alias `backendNodeId`). **Never send any of these as `None`.**
- `options` (TypedDict): `model` (str or model-config object), `timeout` (ms, float),
  `variables: Dict[str, str|float|bool|{value, description?}]`.
- `frame_id` — target an iframe by frame id (alias `frameId`). Relevant for embedded
  payment iframes (insurance) and embedded seat-map widgets (cinema). Same `frame_id` exists on
  observe/extract/navigate.

Verified that `options` round-trips correctly:
```python
maybe_transform({"input":"type %card% into the card field",
  "options":{"model":"anthropic/claude-sonnet-4-6","timeout":15000,
             "variables":{"card":{"value":"4111...","description":"credit card"}}}},
  SessionActParamsNonStreaming)
# -> nested options/variables preserved exactly.
```

### `extract`
```python
session.extract(instruction="...", schema={...json-schema-dict...})
```
- `schema: dict[str, object] | type | None` — a **JSON-Schema dict** (what we use) or a Python
  type. Response: `SessionExtractResponse.data.result` (typed `object` — i.e. whatever the schema
  says). Our `(r.model_dump().get("data") or {}).get("result") or {}` unwrap is correct.
- `extract()` with **no schema** returns free-form text — useful for quick "what does this page say"
  checks but we should keep using schemas for anything we branch on.

### `observe`
```python
session.observe(instruction="...", options={...})
```
- `options` adds `selector` (scope observation to a CSS subtree), `ignore_selectors`
  (exclude noisy nodes — good for blocking analytics/ad DOM that shifts results), plus the same
  `model`/`timeout`/`variables`. Scoping observe with `selector` to the booking widget would make
  our candidate selection far more robust on Ontopo.

### Per-call model override / secrets
- **Model per call**: `options={"model": "anthropic/claude-sonnet-4-6"}` on any of act/observe/extract
  (verified plumbing). Drive cheap steps on Flash, escalate the one hard step to Sonnet without a new
  session.
- **Secrets**: `options={"variables": {"otp": {"value": code, "description": "one-time code"}}}` +
  `input="type %otp% into the code field"`. Values substituted server-side, **not shared with the
  LLM** (per [act docs](https://docs.stagehand.dev/v3/basics/act)). This is the mechanism for the
  insurance card/OTP and any cinema login.

### Bound session
`client.sessions.start(model_name=..., system_prompt=..., ...)` returns an **`AsyncSession`** bound to
the new session id, exposing `act/observe/extract/navigate/execute/replay/end` (verified — matches our
`ontopo.py` usage). Also verified `start` accepts: `self_heal`, `dom_settle_timeout_ms`, `verbose`
(0/1/2), `experimental`, `browser`, `browserbase_session_id` (resume an existing BB session),
`browserbase_session_create_params` (all the Browserbase config — §4).

---

## 4. Browserbase session config

Cited from Browserbase + Stagehand docs.

### Driver / model choice
- Format is **`provider/model`** (required), e.g. `google/gemini-2.5-flash`,
  `anthropic/claude-sonnet-4-6`. ([models](https://docs.stagehand.dev/v3/configuration/models))
- **Documented production default for act/observe/extract = `google/gemini-2.5-flash`**
  ("fast, accurate, cost-effective"). For hardest DOM tasks docs point to a gemini-3 pro preview.
  `anthropic/claude-sonnet-4-6` is a supported first-class model. **`google/gemini-2.5-pro` is no
  longer in the first-class act/observe/extract list** — our configured default is a legacy string;
  move to `gemini-2.5-flash` for routine steps. ([models](https://docs.stagehand.dev/v3/configuration/models))
- **Stagehand docs make *no* claim that Gemini grounds worse than Claude.** Our planned Sonnet
  upgrade is a reasonable empirical bet (and Sonnet is needed for CUA/hybrid agent mode), but it is
  *our* call, not something the docs assert. Don't justify it as "Gemini is weak at grounding" —
  unverified. ([models](https://docs.stagehand.dev/v3/configuration/models))
- **CUA / hybrid agent** (`execute` with `agent_config.mode="cua"|"hybrid"`) needs a coordinate-capable
  model: `anthropic/claude-sonnet-4-6`, `google/gemini-2.5-computer-use-preview-10-2025`,
  `openai/computer-use-preview`. Relevant only if a cinema/insurance site defeats DOM-based act and we
  fall back to pixel control. CUA needs a fixed viewport.
  ([computer-use](https://docs.stagehand.dev/v3/best-practices/computer-use))

### Context reuse / auth persistence (critical for login/OTP — insurance & cinema)
- Create a **Context** once: `POST /v1/contexts` → `bb.contexts.create()` returns a context id.
  ([contexts](https://docs.browserbase.com/features/contexts))
- Resume it per session via `browserbase_session_create_params.browser_settings.context =
  {"id": <ctx>, "persist": true}`. `persist:true` writes cookies/localStorage/IndexedDB/etc. back to
  the context after the run, so the next run is still logged in (survives OTP). Use `persist:false`
  for read-only reuse. ([contexts](https://docs.browserbase.com/features/contexts))
- Operational caveat: wait a few seconds after a session ends before reusing the same context
  (write-back race). ([contexts](https://docs.browserbase.com/features/contexts))
- In our SDK this flows through `sessions.start(browserbase_session_create_params={...,
  "browser_settings": {"context": {"id": ..., "persist": True}}})` (the `BrowserbaseSessionCreateParams`
  TypedDict exposes `browser_settings.context` with `id`+`persist`, verified).

### Proxies / stealth / CAPTCHA
- `proxies: true` (top-level) for US residential, or an array of proxy objects with per-proxy
  `geolocation {country, state, city}`. **Plan-gated: Developer+.** For Israeli sites, target
  `country:"IL"`. ([proxies](https://docs.browserbase.com/features/proxies))
- CAPTCHA solving is **on by default** via `browser_settings.solve_captchas` (default true; up to
  ~30s). Custom captchas: `captcha_image_selector` / `captcha_input_selector`.
  ([stealth](https://docs.browserbase.com/features/stealth-mode))
- Advanced anti-detection: `browser_settings.advanced_stealth` and `verified` browsers —
  **Scale-plan-only**. `os` enum to control UA/environment. Our SDK also exposes
  `browser_settings.fingerprint` (browsers/devices/locales/operating_systems/screen) as a typed param;
  the *current Browserbase API docs* lean on `advancedStealth`/`verified`/`os` instead, so treat the
  fingerprint object as available-but-possibly-legacy. ([stealth](https://docs.browserbase.com/features/stealth-mode),
  [create-session ref](https://docs.browserbase.com/reference/api/create-a-session))
- **`wait_for_captcha_solves`** exists as a start param but is marked **deprecated / v2-only** in our
  SDK (verified); don't rely on it. Same for `act_timeout_ms`. Use event/extract-based waiting instead.

### Session recording & replay / live view
- Recording is automatic (disable with `browser_settings.record_session=false`). Retrieve:
  `GET /v1/sessions/{id}/replays` → `bb.sessions.replays.retrieve(id)`; live debugger URL via
  `bb.sessions.debug(id)` → `debuggerUrl` / `debuggerFullscreenUrl`.
  ([replay](https://docs.browserbase.com/features/session-replay),
  [live view](https://docs.browserbase.com/features/session-live-view))
- Our SDK also exposes **`session.replay()`** → `SessionReplayResponse` with
  `data.pages[].actions[]` (method, parameters, result, timestamp, `token_usage.cost`) — useful both
  for debugging silent failures *and* for per-booking cost accounting (verified type).

### Concurrency & cost controls
- Concurrent sessions per plan: Free 3 / Developer 25 / Startup 100 / Scale 250+; over-limit → 429.
  Session-create rate limits 5/25/50/150 per min. ([concurrency](https://docs.browserbase.com/guides/concurrency-rate-limits))
- **`timeout`** (seconds, 60–21600) on the session is the primary spend cap — auto-ends the session.
  One-minute minimum billing per session. **`keep_alive`** keeps a session alive across disconnects
  (Hobby+); use sparingly — it keeps burning minutes. ([create-session ref](https://docs.browserbase.com/reference/api/create-a-session))
- **`region`** ∈ `us-west-2|us-east-1|eu-central-1|ap-southeast-1` (default us-west-2). Pick the
  region nearest the target site (likely `eu-central-1` for IL sites) to cut latency/wall-clock.
  ([concurrency](https://docs.browserbase.com/guides/concurrency-rate-limits))
- Our `pipeline.BOOKING_TIMEOUT_S = 240` is an app-side `asyncio.wait_for`. Add a matching
  Browserbase session `timeout` so a hung remote session can't outlive (and outbill) our wait.

---

## 5. Error handling

The SDK gives a clean, classifiable exception tree (verified):

| Exception | status_code | Class |
|---|---|---|
| `BadRequestError` | 400 | fatal — bad payload (our old candidate-null bug) |
| `AuthenticationError` | 401 | fatal — bad key |
| `PermissionDeniedError` | 403 | fatal — plan/permission |
| `UnprocessableEntityError` | 422 | fatal — bad schema/args |
| `RateLimitError` | 429 | recoverable — backoff + retry |
| `APITimeoutError` | — | recoverable — retry |
| `APIConnectionError` | — | recoverable — retry |
| `InternalServerError` | 5xx | recoverable — backoff + retry |

All subclass `APIError(StagehandError)`. Recommendations:
- **Classify in `engine._attempt` / `act_verified`** instead of `except Exception`. Map
  recoverable → continue the retry loop (the loop already exists); map fatal (400/401/403/422) →
  break immediately and return an honest failure with the real message (no point re-grounding a
  request the server structurally rejects).
- **Surface real errors.** Today `ontopo.book_table`'s outer `except Exception` collapses every
  failure into `"משהו נתקע באתר"`. Keep the user-facing message friendly, but put
  `type(e).__name__`, `getattr(e, "status_code", None)`, and `str(e)` into `details["error"]` and the
  trace so we can tell a captcha-block (recoverable, retry later) from a 401 (config bug, page us).
- **Partial-progress recovery.** Our flow already records per-step results in `trace`. Extend it:
  on failure, the trace + the **session replay URL** (§4) is enough to resume or diagnose. For the
  multi-step insurance flow, persist "last successful step" so a retry can skip re-doing OTP (which a
  persisted Context already helps with).
- Recoverable-vs-fatal distinction also fixes a current correctness gap: a 429 today is caught,
  logged, and *retried as if the action failed* — re-grounding and possibly double-acting. It should
  back off and retry the *same* action, not escalate the ladder.

---

## 6. Concrete, prioritized changes to our code

Ordered by payoff. Each ties to a verified fact above.

### engine.py
1. **`_clean_candidate`: keep all fields, drop only `None`.** (Top rec #1.) Replace the
   whitelist with `{k: v for k, v in c.items() if v is not None}`. Preserves `backend_node_id`,
   still fixes the 400. *This is a correctness bug today — we discard the deterministic anchor.*
2. **Add act-response no-op detection.** Capture the `act()` return in `_attempt`; if
   `result.data.result.actions` is empty, treat the attempt as failed and escalate immediately
   (cheaper than waiting for the extract check). Thread the response into `trace`.
3. **Classify exceptions** (`isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError,
   InternalServerError))` → recoverable; `BadRequestError/AuthenticationError/PermissionDeniedError/
   UnprocessableEntityError` → fatal, break). Import from `stagehand`.
4. **Replace fixed `SETTLE_S` sleep** with reliance on `dom_settle_timeout_ms` (set at session
   start) + per-call `options.timeout` on slow steps; keep a small residual `settle()` only as a
   backstop.
5. **Optionally accept a per-step `model`/`timeout`** in `act_verified` and pass it via `options`,
   so the playbook can escalate the one flaky step to Sonnet.

### ontopo.py
6. **Pass session-level reliability params**: `self_heal=True`, `dom_settle_timeout_ms=<~5000>`,
   `verbose=2`, and `browserbase_session_create_params={"timeout": 240, "region": "eu-central-1",
   "browser_settings": {"solve_captchas": True}}`. (All verified params.)
7. **Use `variables` for `phone` (and, later, card/OTP/ID)** instead of f-string interpolation into
   `act(input=...)`.
8. **Scope observe with `options.selector`** to the booking-widget container so candidate selection
   stops competing with page chrome/deals.
9. **Record the replay/debug URL** into `details` next to `session_id` for post-mortem on silent
   failures.
10. **The two-shot availability extract (lines ~190-211)** is essentially a manual settle-retry;
    once `dom_settle_timeout_ms` + `options.timeout` are in place it can collapse to one call with a
    longer timeout. Minor simplification.

### Cross-cutting (insurance / cinema engine)
11. **Browserbase Context with `persist:true`** per user, resumed every run — the keystone for
    staying logged in across OTP. Store the context id with the user profile.
12. **Reserve `execute` (agent/CUA) for *discovering* a new, unseen cinema chain**, then freeze the
    learned steps into deterministic act/observe playbook code. Don't run the agent on the hot path.

### What we're doing right (don't change)
- Atomic one-control-per-`act` steps.
- Extract-based semantic verification (`act_verified`'s `ok(state)`) — the SDK's self-heal can't
  replace this.
- `dry_run` confirmation gate before the irreversible step.
- Honest failure surfacing to the user with a real `trace`.
- `resolve.py` doing name→URL off-browser (cheap, no session) — keep; only the DDG-HTML scrape is
  MVP-grade (the file already flags Brave/Serp for prod).

---

## Sources

- Stagehand act basics: https://docs.stagehand.dev/v3/basics/act
- Stagehand observe use case (observe→act): https://docs.stagehand.dev/v3/best-practices/usecase-observe
- Stagehand best practices: https://docs.stagehand.dev/examples/best_practices
- Stagehand caching (TS `cacheDir` — NOT in our Python SDK): https://docs.stagehand.dev/v3/best-practices/caching
- Stagehand deterministic agent scripts: https://docs.stagehand.dev/v3/best-practices/deterministic-agent
- Stagehand models (provider/model, production default): https://docs.stagehand.dev/v3/configuration/models
- Stagehand computer-use / CUA / hybrid agent: https://docs.stagehand.dev/v3/best-practices/computer-use
- Stagehand repo agent rules (atomic act, observe→act): https://github.com/browserbase/stagehand/blob/main/claude.md
- Browserbase blog — AI Web Agent SDK (agent vs primitives): https://www.browserbase.com/blog/ai-web-agent-sdk
- Browserbase Contexts (auth persistence): https://docs.browserbase.com/features/contexts
- Browserbase Proxies + geolocation: https://docs.browserbase.com/features/proxies
- Browserbase Stealth / CAPTCHA: https://docs.browserbase.com/features/stealth-mode
- Browserbase create-session API reference: https://docs.browserbase.com/reference/api/create-a-session
- Browserbase Session Replay: https://docs.browserbase.com/features/session-replay
- Browserbase Session Live View: https://docs.browserbase.com/features/session-live-view
- Browserbase Concurrency & rate limits: https://docs.browserbase.com/guides/concurrency-rate-limits

> SDK-specific claims (ActionParam shape, the `null`→400 reproduction, `options.variables`/`model`
> plumbing, `self_heal`/`dom_settle_timeout_ms` start params, the `execute`/`replay` methods, the
> exception hierarchy, the `to_dict()` double-key bug) were verified by direct introspection of the
> installed `stagehand==3.21.0` in `.venv` on 2026-06-18, not from the web docs.
