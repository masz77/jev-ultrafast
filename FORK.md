# Why this fork exists

Upstream ([browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast)) only talks to TypeSafe's hosted Jev API.
Jev is proprietary: no weights, no self-hosting, and a per-token bill.

This fork lets the same agent run its decisions on a **self-hosted open model**, [Laya](https://github.com/NandhaKishorM/laya) (Apache-2.0).
Laya exposes a Jev-compatible `POST /v1/systemone` endpoint, so the agent needs only a different base URL.

## What changed from upstream

| File | Change |
|---|---|
| `jev_ultrafast/model.py` | Endpoint reads `TYPESAFE_BASE_URL`. Default is still `https://api.typesafe.ai`, so upstream behavior is unchanged. |
| `compose.yaml` (new) | Runs Laya on CPU, bound to `127.0.0.1:8000`, API key required. |
| `laya/` (new) | Git submodule of the Laya repo. It is the Docker build context. |
| `.env.example` | Adds `TYPESAFE_BASE_URL` and `LAYA_API_KEY`. |

The agent still runs on the host (`uv run jev`), not in Docker. It drives your real Chrome over CDP, which a container cannot reach.

## Run it

```bash
git clone --recurse-submodules <this repo> && cd jev-ultrafast
cp .env.example .env   # set LAYA_API_KEY; set TYPESAFE_API_KEY to the same value
docker compose up -d --build
curl -s localhost:8000/health
uv run --env-file .env jev
```

## Known limits (measured on a 8-CPU Docker VM on a Mac, CPU only)

- Latency is about 200 ms per question and about 440 ms for three. Four concurrent clients did not raise throughput much (4.4 req/s).
- Memory use is about 2.1 GiB.
- Laya's checkpoints are not trained for browser navigation. In a smoke test the operation choice was wrong with low confidence, and a 12-case routing test scored 8/12. Expect wrong clicks until you fine-tune on your own traces.
- Laya's default context is 512 to 1024 tokens, so long pages are truncated.
- `TYPE_TEXT` still needs a separate text LLM (`TEXT_MODEL_API_KEY`). Laya cannot write field values.
- The 60-step loop never retries a browser mutation, so a bad choice early can fail the whole run.

Treat this as an experiment, not a drop-in replacement for hosted Jev.

## Staying in sync

`git remote add upstream https://github.com/browser-use/jev-ultrafast.git`, then `git fetch upstream && git merge upstream/main`.
The only upstream file edited is `model.py` (one block), so conflicts should be small.
