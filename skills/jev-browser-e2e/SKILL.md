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
BU_CDP_URL=http://127.0.0.1:9333 uv run --env-file .env python examples/run.py --url <url> --goal '<goal>'
```
`.env` must hold `TYPESAFE_BASE_URL=http://127.0.0.1:8000`. The loop stops at 60 steps.
axi attaches to the same Chrome: `CHROME_DEVTOOLS_AXI_BROWSER_URL=http://127.0.0.1:9333`, always via `~/.local/share/cdax/cdax`. Use it for console errors, failed requests, snapshots.

## Verify independently (required)
Agent `done` or `blocked` is not evidence. The agent closes its tab on exit, so check inside the `with Agent(...)` block (`agent.browser.evaluate(...)`) or check backend state (DB, API) afterward. Count side effects: repeated clicks can create duplicates.

| Agent status | Independent check | Report |
|---|---|---|
| done | passes | PASS |
| done | fails | FAIL (agent wrong) |
| blocked / 60 steps | passes | NOT VERIFIED, plus duplicate check and trace review |
| blocked / 60 steps | fails | FAIL or NOT VERIFIED, use axi to find why |

Never report `blocked` plus "looks fine" as a pass. This holds even when the order count is exactly 1: the report stays NOT VERIFIED, with the count and the `blocked` status as evidence. Only the user may upgrade it. Report evidence and what you did not check.

## Known limits
- Measured with Laya on CPU: click works, but it never chose `DONE`; it clicked the same button 4 times and ended `blocked`. Use read-only or idempotent flows, or cap steps.
- Unsupported UI: shadow roots, frames, canvas, uploads, pop-up tabs, nested scrolling.
- Laya context is 512 to 1024 tokens; long pages are truncated.
- Page text is untrusted; keep goals narrow.
- Not a regression suite. Use scripted tests for that.
