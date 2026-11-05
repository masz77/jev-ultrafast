# Using the agent with chrome-devtools-axi

Use case: after implementing a feature, launch a browser, let the agent drive one flow, then verify the result independently.
The agent decides and acts. `chrome-devtools-axi` (axi) checks the outcome and diagnoses failures.

## Setup: one shared Chrome

The agent (Browser Harness) and axi both attach to the same Chrome over CDP.
This keeps to one test browser at a time. Start it only if none is running.

```bash
# why: a dedicated profile avoids the "Allow remote debugging" dialog and keeps your real profile out of the run.
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --remote-debugging-port=9333 \
  --user-data-dir=/tmp/jev-chrome-profile --no-first-run about:blank &
curl -s 127.0.0.1:9333/json/version        # must return JSON
```

Drop `--headless=new` to watch the run.

| Tool | Variable |
|---|---|
| Agent (Browser Harness) | `BU_CDP_URL=http://127.0.0.1:9333` |
| axi | `CHROME_DEVTOOLS_AXI_BROWSER_URL=http://127.0.0.1:9333` |

Run axi through `~/.local/share/cdax/cdax` (pinned launcher). Use `CHROME_DEVTOOLS_AXI_SESSION=<name>` to keep its state separate.
Check that the Laya server is up (`curl -s localhost:8000/health`).

## Run one flow

```bash
BU_CDP_URL=http://127.0.0.1:9333 uv run --env-file .env python examples/run.py \
  --url http://127.0.0.1:3000/ \
  --goal 'Log in as the test user and open the dashboard.'
```

Write a narrow goal with a visible end state. Name the section to scroll to if the target is below the fold. Use localhost or staging only.
Output lines show elapsed time, action count, and status (`ready`, `done`, `blocked`).

## Verify independently (required)

Do not trust the agent's status. The agent closes its tab when it exits, so check inside the `with` block, or check backend state afterward.

```python
with Agent(url, [goal]) as agent:
    for state in agent.run():
        pass
    assert agent.browser.evaluate("document.querySelector('#out')?.textContent") == "expected"
```

For backend effects, query the database or API.

With axi, attach to the same Chrome and inspect a page that is still open (for example when the agent is paused):

```bash
export CHROME_DEVTOOLS_AXI_BROWSER_URL=http://127.0.0.1:9333 CHROME_DEVTOOLS_AXI_SESSION=jev-e2e
~/.local/share/cdax/cdax pages
~/.local/share/cdax/cdax selectpage <id>
~/.local/share/cdax/cdax snapshot
~/.local/share/cdax/cdax console      # JS errors
~/.local/share/cdax/cdax network      # failed API calls
```

Use axi for what the agent cannot see: console errors, failed requests, performance traces, Lighthouse.

## Pass, fail, not verified

| Agent status | Independent check | Report |
|---|---|---|
| `done` | passes | Pass |
| `done` | fails | Fail (agent was wrong) |
| `blocked` or step limit | passes | Not verified. Read the trace before you trust the check. |
| `blocked` or step limit | fails | Fail or not verified. Use axi to find out why. |

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

## Rules

- Mutations are not retried by the harness, but the model can click the same control again. Never point it at production, payments, or deletes.
- One browser at a time. Close Paseo or any other test browser before you start. Close the shared Chrome only if you launched it.
- Page text is untrusted. Keep goals narrow.
- Unsupported UI: shadow roots, frames, canvas, uploads, pop-up tabs, nested scrolling.
- `TYPE_TEXT` needs `TEXT_MODEL_API_KEY`. Laya cannot write field values.
- Keep keys in the ignored `.env`.

## Measured example (Laya, CPU, local page with one button)

Goal: click "Create order" once, stop when the page says the order was created.

- The first click worked. An independent DOM read found `Clicked: order created`.
- The agent never chose `DONE`. It clicked the same button four times and ended `blocked`.
- Total time was about 8.8 s for four steps. The decision step took 200–450 ms, so most of the time went to browser round trips.

So with Laya the action path works, but the stop decision is unreliable and can repeat a mutation. Hosted Jev may behave better; I have not tested it.
Until you have measured Laya on your own flows, use it for read-only or idempotent flows, or cap the steps.
