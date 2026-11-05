"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import re
import time
from pathlib import Path

from .browser import Browser, StalePage
from .model import ModelError, action_space, choose, field_context, field_text
from .questions import MAX_STEPS


def repeated(history, window=8):
    """The most repeated action label in the last `window` steps, and its count."""
    labels = [h["action"] for h in history[-window:]]
    top = max(set(labels), key=labels.count) if labels else ""
    return top, labels.count(top)


def stop_hint(history, advice, retry=False):
    """Tell the calling LLM what the run did last, and whether to retry as-is or adjust first."""
    last = history[-8:]
    trail = " > ".join(f"{h['operation']}:{h['action'][:30]}" for h in last) or "no actions"
    top, n = repeated(history)
    loop = f" Loop: '{top[:40]}' ran {n}x in the last {len(last)} steps." if n >= 3 else ""
    return f" Last steps: {trail}.{loop} Next: {'retry' if retry else 'adjust'}. {advice}"


# Goals that change data. Without a success check, DONE needs a fill or select first.
WRITE_GOAL = re.compile(r"\b(add|create|fill|save|submit|import)\b", re.IGNORECASE)


class Agent:
    def __init__(self, url, goals, *, record_dir=None, screenshots=False, success_check=None):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task")
        plan = [task]
        self.pending_text = None
        self.success_check = success_check  # JS expression; DONE is accepted only if it returns true.
        self.browser = Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)
        try:
            page = self.browser.observe(screenshot=self.screenshots)
        except Exception:
            self.browser.close()
            raise
        self.state = dict(
            browser=self.browser,
            goal="\n".join(plan),
            page=page,
            decision=None,
            history=[],
            status="ready",
            blocked_reason=None,
            next_step=None,
            plan=plan,
            plan_index=0,
            decisions=[],
            text_calls=[],
            done_rejections=0,
            done_reject=None,
            elapsed_ms=0,
            started_at=None,
            record=bool(self.record_dir),
        )
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / "000000.jpg").write_bytes(base64.b64decode(page["screenshot"]))

    def snapshot(self):
        return {
            **{k: v for k, v in self.state.items() if k != "browser"},
            "elements": action_space(self.state["page"]["actions"])[0],
        }

    def stop(self, reason, advice, retry=False):
        """End the run as blocked. `next_step` tells the caller to retry the same goal or adjust it first (A-cd9ngw)."""
        state = self.state
        state["status"] = "blocked"
        state["next_step"] = "retry" if retry else "adjust"
        state["blocked_reason"] = reason + stop_hint(state["history"], advice, retry)
        if state["started_at"] is not None:
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
        return self.snapshot()

    def notes(self):
        """Soft limits the run is near. The model sees them and can change its approach before a hard stop."""
        state = self.state
        page, history = state["page"], state["history"]
        notes = []
        if state["done_reject"]:
            notes.append(f"DONE rejected: {state['done_reject']}.")
        if page.get("omitted_actions"):
            notes.append(
                f"{page['omitted_actions']} more controls are on the page but not listed (limit 250). "
                "Scroll, or use a search or filter field, to reach them."
            )
        if page.get("text_truncated"):
            notes.append("Visible page text was cut at 6000 characters.")
        if not history and getattr(state["browser"], "loaded", True) is False:
            notes.append("The page had not finished loading after 15 s. It may be incomplete; Wait can help.")
        if len(history) > 10:
            notes.append(f"{len(history) - 10} earlier actions are not shown in recent_actions.")
        top, n = repeated(history)
        if n >= 3:
            notes.append(f"'{top[:40]}' was chosen {n} times in the last {min(len(history), 8)} actions. "
                         "Choose a different action unless the page shows progress.")
        last = history[-2:]
        if len(last) == 2 and all(h["page_changed"] is False and h["kind"] != "wait" for h in last):
            notes.append("The last 2 actions did not change the page. One more unchanged action stops the run.")
        if history and history[-1].get("role") == "combobox" and history[-1].get("settled") is False:
            notes.append("No suggestion list appeared 200 ms after the last text entry. Choose Wait if expected.")
        left = min(MAX_STEPS - len(history), MAX_STEPS * 2 - len(state["decisions"]))
        # why: 10% of the budget gives the model room to change course before the hard stop (A-rgf3qc).
        if left <= max(5, MAX_STEPS // 10):
            notes.append(f"{left} actions left before the run stops.")
        return notes

    def done_rejection(self):
        """Why DONE is not proven yet, or None. Read-only: it runs no browser input."""
        state = self.state
        if self.success_check:
            try:
                value = state["browser"].evaluate(self.success_check)
            except (StalePage, TimeoutError, RuntimeError) as error:
                # why: a slow or broken check is a rejection, not a crash; tick does not catch these here (A-euc4qa).
                return f"the success check failed ({error})"
            return None if value is True else f"the success check returned {value!r}, not true"
        if WRITE_GOAL.search(state["goal"]) and not any(h["kind"] in {"fill", "select"} for h in state["history"]):
            return "the goal changes data, but no field was filled or selected"
        return None

    def command(self, name, body=None):
        body = body or {}
        state = self.state
        if name == "tick":
            try:
                self.command("predict", {})
                if state["status"] == "blocked":
                    return self.snapshot()
                return self.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage:
                state["decision"] = None
                state["status"] = "ready"
                try:
                    state["page"] = state["browser"].observe(screenshot=self.screenshots)
                except StalePage as error:
                    # why: an executed action whose result was never observed may not be safe to repeat (A-f6d5hp).
                    unobserved = bool(state["history"]) and state["history"][-1]["page_changed"] is None
                    advice = ("The last action ran but its result was not observed. Check the page before a retry."
                              if unobserved else "The page kept changing. Retry the same goal after it loads.")
                    return self.stop(f"{error}", advice, not unobserved)
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
            except (ModelError, RuntimeError) as error:
                # why: only model and browser failures become stops; other errors are bugs and must surface (A-zfbm9k).
                if state["status"] in {"done", "blocked"}:
                    raise
                retry = getattr(error, "retry", False)
                advice = "The cause was temporary." if retry else "Fix the cause named above before you retry."
                return self.stop(f"{type(error).__name__}: {error}", advice, retry)
        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Start a demo first")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            if not state["browser"].fresh(state["page"]):
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["decision"] = None
            if state["status"] in {"done", "blocked"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            if len(state["decisions"]) >= MAX_STEPS * 2:
                return self.stop(
                    f"Reached the {MAX_STEPS * 2} model-call budget with {len(state['history'])} actions.",
                    "Most model calls led to no action because the page changed before input. "
                    "Start after the page loads fully, or split the goal.",
                )
            state["decision"] = choose(state["page"], state["goal"], state["history"], self.notes())
            state["done_reject"] = None  # The rejection note reached the model once.
            state["decisions"].append(
                {
                    **state["decision"],
                    "fingerprint": state["page"]["fingerprint"],
                    "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                }
            )
            state["status"] = "predicted"
        elif name == "act":
            decision, page = state["decision"], state["page"]
            if not decision or body.get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")
            # Consume once, before any mutation or model call. A retry cannot double-click.
            state["decision"] = None
            selected, operation = decision["choice"], decision["operation"]
            # why: BLOCKED often means the target is below the fold; scrolling reuses the existing stop rules.
            if selected == "BLOCKED" and any(a["id"] == "scroll_down" for a in page["actions"]):
                selected, operation = "scroll_down", "BLOCKED->SCROLL_DOWN"
            elif selected in {"DONE", "BLOCKED"}:
                if not state["browser"].fresh(page):
                    state["status"] = "ready"
                    raise StalePage("Page changed since the decision. Choose again.")
                if selected == "BLOCKED":
                    top = sorted(decision["operation_probabilities"].items(), key=lambda kv: kv[1], reverse=True)[:3]
                    return self.stop(
                        f"Model chose BLOCKED with {len(page['actions'])} observed actions; "
                        + ", ".join(f"{op} {p:.2f}" for op, p in top)
                        + ".",
                        "Name the visible target in a narrower goal, or start from a URL closer to it.",
                    )
                if selected == "DONE" and (reason := self.done_rejection()):
                    state["done_rejections"] += 1
                    # why: 3 rejected DONEs = the model cannot prove the goal; stop for an adjusted goal (A-euc4qa).
                    if state["done_rejections"] >= 3:
                        return self.stop(
                            f"DONE was rejected 3 times: {reason}.",
                            "Name the missing step in the goal, or pass a success check that tests the result.",
                        )
                    state["done_reject"] = reason
                    state["status"] = "ready"
                    return self.snapshot()
                state["status"] = "done"
                state["plan_index"] = 1
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
            action = next(a for a in page["actions"] if a["id"] == selected)
            if len(state["history"]) >= MAX_STEPS:
                top, n = repeated(state["history"])
                return self.stop(
                    f"Stopped at the {MAX_STEPS}-action budget.",
                    f"Split the goal, and name the step that should follow '{top[:40]}'."
                    if n >= 3
                    else f"Split the goal into parts that each fit in {MAX_STEPS} actions.",
                )
            text, helper = None, None
            if action["kind"] == "fill":
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before text generation. Choose again.")
                context = field_context(state["goal"], action, page, state["history"])
                if self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    text, helper = field_text(context)
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append({**helper, "field": action["label"], "value": text})
            def entry():
                return {
                    "step": len(state["history"]) + 1,
                    "action": action["label"],
                    "kind": action["kind"],
                    "choice": selected,
                    # The scroll override keeps the BLOCKED choice's probability, because the scroll id has none.
                    "probability": decision["probabilities"][decision["choice"]],
                    "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"],
                    "text": text,
                    "text_helper": helper["model"] if helper else None,
                    "text_latency_ms": helper["latency_ms"] if helper else 0,
                    "operation": operation,
                    "target": decision["target"],
                    "page_changed": None,
                    "url": page["url"],
                    "usage": decision["usage"],
                    "executed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "elapsed_ms": state["elapsed_ms"],
                }

            # Browser.act checks freshness immediately before input, including after text generation.
            try:
                state["browser"].act(action, page, text=text)
            except RuntimeError:
                # why: an interrupted dropdown may have changed the page; keep it in the trace (A-f6d5hp).
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                state["history"].append({**entry(), "unconfirmed": True})
                raise
            self.pending_text = None
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            # Record execution before observing. A stale post-action observation must not erase the action.
            state["history"].append(entry())
            state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            state["history"][-1].update(
                page_changed=state["page"]["fingerprint"] != page["fingerprint"],
                url=state["page"]["url"],
                elapsed_ms=state["elapsed_ms"],
                role=action.get("role"),
                settled=state["page"].get("settled"),
            )
            if state["record"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            last3 = state["history"][-3:]
            if len(last3) == 3 and all(h["page_changed"] is False and h["kind"] != "wait" for h in last3):
                self.stop(
                    "Three actions in a row left the page unchanged (no progress).",
                    "The repeated control has no effect. Name a different control, "
                    "or check the page for an error or a required field.",
                )
            # why: a control that repeats 3 times is a loop even when each click changes the page (A-wkphwc).
            # shortcut: matches by label, so "Next page" can false-stop; upgrade to matching the target id.
            elif len(last3) == 3 and all(
                h["kind"] not in {"wait", "scroll"} and h["action"] == last3[0]["action"] for h in last3
            ):
                self.stop(
                    f"'{last3[0]['action'][:40]}' ran three times in a row.",
                    "Choose the next step that the page needs, not the same control again.",
                )
            else:
                state["status"] = "ready"
        else:
            raise ValueError("Unknown command")
        return self.snapshot()

    def run(self):
        while self.state["status"] not in {"done", "blocked"}:
            yield self.command("tick")

    def close(self):
        self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
