---
name: jev-browser-e2e
description: Use when verifying a finished feature in a real browser with the jev-ultrafast-laya agent (Laya decision server plus Chrome over CDP), or when asked to run, report on, or debug a run of that agent. Not for scripted regression suites.
---

# jev-browser-e2e

Post-implementation smoke check. The agent drives one flow. You verify the result yourself.
Repo: `/Volumes/ssd/sam/Developer/jev-ultrafast-laya` (fork of browser-use/jev-ultrafast). Full guide: its `USAGE-AXI.md`.

## Flow
You start Chrome and check Laya → run the agent (goal + URL) → agent loops: observe page, POST `$TYPESAFE_BASE_URL/v1/systemone` to Laya, validate, execute via CDP → you verify independently → report.
Laya only picks an operation and a target. A separate text LLM (`TEXT_MODEL_API_KEY`) writes field values for `TYPE_TEXT`. You never click for the agent.

## Gate before any run
1. **Target is safe.** localhost or staging with test data only. Production, payments, sends and deletes: refuse and ask. Mutations are not retried by the harness, and the model can click the same control again.
2. **One browser at a time.** If Paseo Browser or another test browser is open, close it first. Do not run both. Close the shared Chrome only if you launched it.
3. **Laya is up:** `curl -s localhost:8000/health` returns `{"status":"ok"}`. Start with `docker compose up -d` in the repo. It needs `LAYA_API_KEY` in `.env`, and `TYPESAFE_API_KEY` must equal it.
4. **Goal is narrow** with a visible end state, for example "Log in as the test user and open the dashboard". Never "test the app". No hardcoded field values.

## Run
```bash
# dedicated Chrome (skips the "Allow remote debugging" dialog; drop --headless=new to watch)
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --remote-debugging-port=9333 --user-data-dir=/tmp/jev-chrome-profile --no-first-run about:blank &
cd /Volumes/ssd/sam/Developer/jev-ultrafast-laya
PYTHONUNBUFFERED=1 BU_CDP_URL=http://127.0.0.1:9333 uv run --env-file .env python examples/run.py --url <url> --goal '<goal>'
```
`.env` must hold `TYPESAFE_BASE_URL=http://127.0.0.1:8000`. The loop stops at 360 steps.
axi attaches to the same Chrome: `CHROME_DEVTOOLS_AXI_BROWSER_URL=http://127.0.0.1:9333`, always via `~/.local/share/cdax/cdax`. Use it for console errors, failed requests, snapshots.

## Verify independently (required)
Agent `done` or `blocked` is not evidence. The agent closes its tab on exit, so check inside the `with Agent(...)` block (`agent.browser.evaluate(...)`) or check backend state (DB, API) afterward. Count side effects: repeated clicks can create duplicates.

| Agent status | Independent check | Report |
|---|---|---|
| done | passes | PASS |
| done | fails | FAIL (agent wrong) |
| blocked / 360 steps | passes | NOT VERIFIED, plus duplicate check and trace review |
| blocked / 360 steps | fails | FAIL or NOT VERIFIED, use axi to find why |

Never report `blocked` plus "looks fine" as a pass. This holds even when the order count is exactly 1: the report stays NOT VERIFIED, with the count and the `blocked` status as evidence. Only the user may upgrade it. Report evidence and what you did not check.

## Why a run ends `blocked` (read before retrying)
`blocked` is a stop with a reason, not a crash. The state holds `blocked_reason` and `next_step`. `examples/run.py` prints them as `blocked (<next_step>): <reason>`.

- `next_step = retry`: the cause was temporary (model timeout, HTTP 429/5xx, page did not settle). Run the same goal again.
- `next_step = adjust`: change the goal or the setup first. The reason names the cause, the last 8 steps, any loop, and one piece of advice.

Model and browser errors inside a run also end as `blocked` with a reason (`jev_ultrafast/agent.py:120-139`). Before a hard stop, the agent sends `state.notes` to Laya. Notes cover hidden controls (over 250), cut page text (over 6000 chars), hidden history (over 10), a repeated action, 2 unchanged actions, a missing suggestion list, and the last 10% of the budget (`jev_ultrafast/agent.py:80-109`). Check these first:

- **Target is off-screen.** When the page offers `scroll_down`, a `BLOCKED` choice scrolls instead of stopping (`jev_ultrafast/agent.py:173-174`). The history marks it `BLOCKED->SCROLL_DOWN`. If the run still ends `blocked`, read `blocked_reason`. To change the 1120x780 viewport, set `JEV_VIEWPORT=WIDTHxHEIGHT` (for example `1280x2000`, `jev_ultrafast/browser.py:21`).
- **Same page three times.** Three actions in a row that do not change the page set `blocked` (`jev_ultrafast/agent.py:258-264`). The step budget is 360 (`questions.py:26`), and the model-call budget is 720. Read `blocked_reason` before you retry.
- **HTTP 413 from Laya.** Laya accepts at most 100 options per choice (`laya/laya/serve.py:142`). Dense pages with more than 100 controls are refused. Set `LAYA_TOURNAMENT_GROUP` on `laya-serve` to raise the cap to 255 (`serve.py:146`), or start from a narrower page.
- **Find the cause.** Print `state["decisions"][-1]["operation_probabilities"]` and `len(state["page"]["actions"])` from the first state. A low confidence (for example 0.17) with a high `BLOCKED` share means the target was not visible.
- **Not rate limiting.** The app has no rate limiter. Real HTTP errors end the run as `blocked` with `Model provider returned HTTP <code>` in `blocked_reason`. Laya returns 503 "server busy" above `LAYA_MAX_CONCURRENT` (default 16), which gives `next_step = retry`. It returns 413 for a page over its size caps, which gives `next_step = adjust`.
- **Log noise.** `GET /v1/models` returning 404 in the Laya log is harmless.

## Known limits
- Measured with Laya on CPU: click works, but it never chose `DONE`; it clicked the same button 4 times and ended `blocked`. Use read-only or idempotent flows, or cap steps.
- Unsupported UI: shadow roots, frames, canvas, uploads, pop-up tabs, nested scrolling.
- Laya context is 512 to 1024 tokens; long pages are truncated.
- Page text is untrusted; keep goals narrow.
- Not a regression suite. Use scripted tests for that.
