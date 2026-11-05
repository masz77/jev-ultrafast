"""uv run --env-file .env python examples/run.py --url URL --goal 'A narrow goal'"""

import argparse

from jev_ultrafast import Agent

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--goal", action="append", required=True, help="Repeat for an ordered list of goals.")
parser.add_argument("--success-check", help="JavaScript expression that must return true before DONE is accepted.")
args = parser.parse_args()

with Agent(args.url, args.goal, success_check=args.success_check) as agent:
    for state in agent.run():
        print(f"{state['elapsed_ms']:>5} ms  {len(state['history'])} actions  {state['status']}")
    print(state["page"]["url"])
    if state["status"] == "blocked":  # next_step: "retry" the same goal, or "adjust" it first.
        print(f"blocked ({state['next_step']}): {state['blocked_reason']}")
