# Why this fork exists

Upstream ([browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)) only talks to TypeSafe's hosted Jev API.
Jev is proprietary: no weights, no self-hosting, and a per-token bill.

This fork runs the same agent on a **self-hosted open model**, [Laya](https://github.com/NandhaKishorM/laya) (Apache-2.0).
Laya exposes a Jev-compatible `POST /v1/systemone` endpoint, so the agent needs only a different base URL.

Treat this fork as an experiment, not a drop-in replacement for hosted Jev (see [Known limits](#known-limits)).

## What changed from upstream

| File | Change |
|---|---|
| `jev_ultrafast/model.py` | Endpoint reads `TYPESAFE_BASE_URL`. Default is still `https://api.typesafe.ai`, so upstream behavior is unchanged. |
| `compose.yaml` (new) | Runs Laya on CPU, bound to `127.0.0.1:8000`, API key required. |
| `laya/` (new) | Git submodule of the Laya repo. It is the Docker build context. |
| `.env.example` | Adds `TYPESAFE_BASE_URL` and `LAYA_API_KEY`. |

The agent still runs on the host (`uv run jev`), not in Docker. It drives your real Chrome over CDP, which a container cannot reach.

## Setup

```bash
git clone --recurse-submodules <this repo> && cd jev-ultrafast
cp .env.example .env   # set LAYA_API_KEY; set TYPESAFE_API_KEY to the same value
docker compose up -d --build
curl -s localhost:8000/health
uv run --env-file .env jev
```

## Intended usage

Use the agent as a post-implementation smoke check, driven by a coding LLM.
After a feature is built, the LLM launches a browser, lets the agent run one flow, then verifies the result itself.
Full steps: [USAGE-AXI.md](USAGE-AXI.md). The LLM skill: [`skills/jev-browser-e2e/SKILL.md`](skills/jev-browser-e2e/SKILL.md).

### Install the skill (Claude Code)

```bash
mkdir -p ~/.claude/skills && cp -R skills/jev-browser-e2e ~/.claude/skills/    # all projects
# or per project: cp -R skills/jev-browser-e2e <project>/.claude/skills/
```

1. Edit the repo path and Chrome path inside `SKILL.md` if yours differ. The file uses `/Volumes/ssd/sam/Developer/jev-ultrafast-laya`.
2. Start a new Claude Code session so it loads the skill.

### Use the skill

First, start Docker and Laya (`docker compose up -d`, then `curl -s localhost:8000/health`).
Then ask in plain words after you finish a feature. The skill triggers on a browser check with this agent:

> Use the jev-ultrafast-laya agent to verify the login flow on http://localhost:3000 and tell me PASS, FAIL or NOT VERIFIED.

You can also call `/jev-browser-e2e` directly, then give the URL and the goal.

The LLM then checks the target is safe, closes any other test browser, starts Chrome, runs the agent, verifies the result itself, and reports.

```
coding LLM → starts Chrome (CDP :9333) + checks Laya /health
           → runs the agent (goal + URL)
agent loop → observes page → POST /v1/systemone to Laya → validates → executes via CDP
           (a separate text LLM writes field values for TYPE_TEXT only)
coding LLM → verifies independently (DOM read, DB/API, axi for console and network)
           → reports PASS / FAIL / NOT VERIFIED
```

### Roles

- **Laya** picks an operation and a target.
- **The agent** executes.
- **The coding LLM** verifies and reports.
- **axi** (`chrome-devtools-axi`) attaches to the same Chrome for console errors, failed requests and snapshots.

### Rules

- **One shared Chrome** on a dedicated profile. Run one test browser at a time: close Paseo or any other first.
- **Safe targets only:** localhost or staging with test data. Never production, payments, sends or deletes.
- **Narrow goals** with a visible end state, for example "log in as the test user and open the dashboard".
- **The agent's status is not a verdict.** `done` and `blocked` are not evidence. A `blocked` run stays NOT VERIFIED until the independent check and a duplicate-side-effect check are done.
- **Not for regression suites.** Use scripted tests for repeatable checks.

## Known limits

Measured on an 8-CPU Docker VM on a Mac, CPU only.

**Performance**
- Latency is about 200 ms per question and about 440 ms for three.
- Four concurrent clients did not raise throughput much (4.4 req/s).
- Memory use is about 2.1 GiB.

**Model quality**
- Laya's checkpoints are not trained for browser navigation. In a smoke test the operation choice was wrong with low confidence, and a 12-case routing test scored 8/12. Expect wrong clicks until you fine-tune on your own traces.
- Laya's default context is 512 to 1024 tokens, so long pages are truncated.
- `TYPE_TEXT` still needs a separate text LLM (`TEXT_MODEL_API_KEY`). Laya cannot write field values.

**Agent behavior**
- The 60-step loop never retries a browser mutation, so a bad early choice can fail the whole run.
- In a one-button test the agent clicked correctly but never chose `DONE`. It clicked the same button 4 times and ended `blocked`.
- Use idempotent or read-only flows until you have measured Laya on your own pages.

## Staying in sync

```bash
git remote add upstream https://github.com/browser-use/jev-ultrafast.git
git fetch upstream && git merge upstream/main
```

The only upstream file edited is `model.py` (one block), so conflicts should be small.
