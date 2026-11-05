---
type: Architecture
title: Run limits and stop reasons
description: Every limit warns the model before it binds, and every stop gives the calling LLM a reason plus retry or adjust.
timestamp: 2026-11-05
tags: [limits, budget, stop, blocked, laya]
---

# Run limits and stop reasons

## Overview

The agent has hard limits: an action budget, a model-call budget, a no-progress rule, and size caps on what the model sees. Laya has its own caps. Before 2026-11-05, most limits stopped the run without a reason, or crashed it. The calling LLM could not tell whether to run the same goal again or change it.

Now each limit does two things:

1. **Before it binds:** the agent sends a short note to Laya in `state.notes`, so the model can change its approach.
2. **When it binds:** the run ends with `status = blocked`, `next_step = retry | adjust`, and a `blocked_reason` that names the cause, the last 8 steps, any loop, and one piece of advice.

A stop is not a crash. The run returns normally and the caller decides what to do next.

## Architecture Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| A-es5q8r | Action budget | `MAX_STEPS = 360` (was 60). Model-call budget follows at `MAX_STEPS * 2` = 720 (`jev_ultrafast/questions.py:28`, `jev_ultrafast/agent.py:150`). | 60 was a demo number with no documented reason (it came in the first commit, `68c077b`). A real filter flow used all 60 actions before it finished. The budget still guards against loops and caps cost. The no-progress rule still stops a stuck page after 3 actions, so a higher budget does not make a stuck run longer. |
| A-rgf3qc | Warn before a hard limit | `Agent.notes()` (`jev_ultrafast/agent.py:80-109`) sends notes only when one applies: more than 250 controls (some not listed), page text cut at 6000 chars, more than 10 actions (older ones not shown), one action repeated 3+ times in the last 8, 2 unchanged actions in a row, no suggestion list after typing, first page not loaded after 15 s, last 10% of the budget. Notes go **first** in `state` (`jev_ultrafast/model.py:130-131`). | A hard stop wastes the run. A note lets the model scroll, filter or choose a different action first. Laya cuts a dict state from the end at its token limit (`laya/laya/common.py:205`), so notes at the start survive a cut. With no notes, the request is the same as before. 10% (at least 5) gives the model room to change course. |
| A-cd9ngw | Every stop gives a reason and `next_step` | `Agent.stop()` (`jev_ultrafast/agent.py:70-78`) sets `status`, `next_step` and `blocked_reason` through `stop_hint()` (`agent.py:19-25`). Budgets no longer raise. `ModelError` (`jev_ultrafast/model.py:15-20`) carries `retry`. `retry` = temporary cause: connection error, HTTP 429/5xx, page never settled. `adjust` = the same goal fails again: HTTP 413, missing API key, missing field value (`{"text": null}`), budget used up, model chose BLOCKED, 3 unchanged actions. | The calling LLM must know whether to run the same goal again or change it. Without this, it repeats a goal that cannot pass. HTTP 413 is a real case: Laya refuses a choice over 100 options (`laya/laya/serve.py:142`; 255 with `LAYA_TOURNAMENT_GROUP`, `serve.py:146`). On the local Laya server, a page with 120 controls returned 413. The 413 advice names `LAYA_TOURNAMENT_GROUP`. |
| A-zfbm9k | Which errors become a stop | `tick` converts only `ModelError` and `RuntimeError` (`jev_ultrafast/agent.py:133-139`). Other exceptions, for example `KeyError`, still raise. | A broad catch would turn programming bugs into a normal `blocked` state and hide them. The demo server still answers HTTP 500 for those bugs (`jev_ultrafast/demo.py:122-123`). Found by Codex review round 1. |
| A-euc4qa | DONE needs proof | `DONE` is accepted only if `success_check` returns exactly `true`, or, for a goal that adds, creates, fills, saves, submits or imports, after one `fill` or `select` (`jev_ultrafast/agent.py:WRITE_GOAL`, `done_rejection`). An error while evaluating the check (`StalePage`, `TimeoutError`, `RuntimeError`) is a rejection too. A rejected DONE sets `status = ready` and a note `DONE rejected:` for the next choose. The third rejected DONE stops `blocked`, `adjust`. | A real run clicked "Pipeline" 3 times and then said DONE; nothing was created. The check reads the page only and runs no input. A 3-strike stop stops a model that cannot prove the goal from looping on DONE. |
| A-wkphwc | Same control three times is a loop | Three actions with the same label in a row, excluding `wait` and `scroll` kinds, stop `blocked`, `adjust` (`jev_ultrafast/agent.py`, after the no-progress check in `act`), even when each click changed the page. | A re-rendered page beat the no-progress rule, so a control could repeat forever. The rule is a label match, so a repeated label such as "Next page" can stop a run that makes progress; this is a `shortcut`. |
| A-f6d5hp | Never mark a mutation for retry | If an action ran but its result was not observed, the stop is `adjust`, not `retry` (`jev_ultrafast/agent.py:120-131`). An interrupted dropdown is logged in history with `unconfirmed: true` before the error ends the run (`agent.py:234-241`). | AGENTS.md: "Never retry a browser mutation. Log execution before observing its result." A `retry` after an unobserved click could repeat it, for example a second order. Found by Codex review round 1. |

## Key Files

| File | Purpose |
|------|---------|
| `jev_ultrafast/questions.py` | `MAX_STEPS` |
| `jev_ultrafast/agent.py` | `repeated`, `stop_hint`, `Agent.stop`, `Agent.notes`, stop conversion in `tick` |
| `jev_ultrafast/model.py` | `ModelError`, HTTP advice in `post_json`, `notes` in `choose`, missing-value check in `field_text` |
| `jev_ultrafast/browser.py` | `settled` after input, `loaded` after first navigation |
| `jev_ultrafast/snapshot.js` | `omitted_actions` (over 250 controls), `text_truncated` (6000 chars) |
| `jev_ultrafast/static/app.js` | Shows `blocked_reason` with Retry or Adjust in the demo UI |
| `examples/run.py` | Prints `blocked (<next_step>): <reason>` |
| `tests/test_agent.py` | Offline tests for each stop, each note, and both mutation rules |

## Limits not changed

- Laya caps (`laya/laya/serve.py:95-148`): 100 options per choice, 512 options in total, 50 000 state chars. These belong to the Laya submodule. The agent reports them through the HTTP 413 advice.
- Input checks: goal 1-2000 chars (`demo.py:51`), request body under 8192 bytes (`demo.py:115`), text value 1-2000 chars (`model.py`). These are trust-boundary checks, not run limits.
- `scripts/smoke.py --max-actions` (default 15) is a diagnostic cap. Its message now says how to change it.

## Open

- Laya's model was not trained on `notes`. There is no evidence yet that it acts on them.
- No full live browser run has been made with these changes. Only the model calls were tested on the local Laya server (413 path and `notes`).
