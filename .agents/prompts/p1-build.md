# p1-build: make `blocked` runs diagnosable and fix the off-screen-target trap

Repo: /Volumes/ssd/sam/Developer/jev-ultrafast-laya (read AGENTS.md and README.md first). Python, uv.

## Context (verified)
- Laya picked BLOCKED on step 1 because the target (a button at y=1411, viewport 780) was outside the viewport. Observation only lists in-viewport elements (jev_ultrafast/browser.py:64-65 area, snapshot.js:102 adds `{id:'scroll_down',kind:'scroll',delta:560}` only when more page is below).
- agent.py `act` branch: `if selected in {"DONE","BLOCKED"}` (~line 93) sets status "blocked" with no reason. Other blocked sites: MAX_STEPS (~line 102) and the 3-unchanged-actions rule (~line 151-156).
- Viewport is hard-coded: browser.py:25 `Emulation.setDeviceMetricsOverride width=1120, height=780`.
- history entry is built from `decision["probabilities"][selected]` (agent.py ~line 125); for BLOCKED, `probabilities` only has the "BLOCKED" key.
- Scroll execution is `browser_operation` kind == "scroll" (browser.py ~138). Scrolling is non-mutating.

## Task (all three must be true when done)
1. **Blocked reason.** Whenever status becomes "blocked", set `state["blocked_reason"]` to one short string, one per site: model chose BLOCKED (include number of observed actions and the top 3 `operation_probabilities`), no-progress (3 unchanged actions), step budget. It must appear in `snapshot()` (it does if it lives in state; initialise it to None in `__init__`). `examples/run.py` prints `blocked: <reason>` after the loop when status is blocked.
2. **BLOCKED -> scroll.** In `act`, when the model's choice is "BLOCKED" and the observed page offers an action with id `scroll_down`, do not stop: execute that scroll action instead through the normal action path (same freshness check, history entry, page_changed bookkeeping). Mark the history entry so it is visible (e.g. `"operation": "BLOCKED->SCROLL_DOWN"`). Handle the probability lookup safely (no KeyError). No new model call. Bounded by existing rules: scroll_down disappears at page bottom, then BLOCKED stops as before; the 3-unchanged rule and MAX_STEPS still apply. If the page has no scroll_down, BLOCKED behaves exactly as today. DONE is untouched.
3. **Viewport.** Add optional env `JEV_VIEWPORT` as `WIDTHxHEIGHT` (e.g. `1280x2000`), default stays 1120x780 (no behaviour change when unset). Invalid value raises ValueError with a clear message. Parse it in one small function in browser.py. Use at browser.py:25.
4. **Docs.** Update USAGE-AXI.md and skills/jev-browser-e2e/SKILL.md section "Why a run ends `blocked`": say that BLOCKED now scrolls when more page is below, that `blocked_reason` is in the state and printed by run.py, and document `JEV_VIEWPORT`. Keep it short; fix any sentence that becomes untrue. Add `JEV_VIEWPORT` as a commented example line to .env.example. README: add one line only if README documents env vars or BLOCKED behaviour that is now wrong; check with grep.

## Tests (80/20, write first, offline, no paid API)
In tests/test_agent.py, using the existing `runner` fixture style:
- BLOCKED with `scroll_down` in page actions -> `browser.act` called once with the scroll action, status "ready", history[-1] marks the override. Control: BLOCKED with no scroll_down -> status "blocked", `act` not called, `blocked_reason` is a non-empty string containing the count of observed actions.
- No-progress rule sets a `blocked_reason` mentioning unchanged actions.
- `JEV_VIEWPORT` parser: "1280x2000" -> (1280, 2000); unset -> (1120, 780); "bad" -> ValueError.
Expected values are fixed by this brief; do not weaken any existing assertion.

## Owned files
jev_ultrafast/agent.py, jev_ultrafast/browser.py, examples/run.py, tests/test_agent.py, USAGE-AXI.md, skills/jev-browser-e2e/SKILL.md, .env.example, README.md (only if needed). Everything else is read-only. Do not touch laya/.

## Done when
`uv run ruff check .` clean; `uv run pytest` all pass (report counts); `node --check jev_ultrafast/static/app.js`; `uv build` succeeds. Do not run the live browser; the orchestrator does that.
