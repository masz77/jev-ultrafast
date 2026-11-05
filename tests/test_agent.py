"""Offline contracts for a dynamic operation/target policy. No paid APIs."""

import json
import time
from copy import deepcopy
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import browser as browser_mod
from jev_ultrafast import model
from jev_ultrafast.browser import StalePage, browser_operation, fingerprint


def page():
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def choice(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(action="e1"):
    return {
        "choice": action,
        "operation": "TYPE_TEXT",
        "target": "1",
        "confidence": 1.0,
        "probabilities": {action: 1.0},
        "latency_ms": 10,
        "usage": {},
    }


@pytest.mark.parametrize("mutation", ["unknown", "nan", "missing", "negative", "non_max", "confidence"])
def test_invalid_choice_is_rejected(mutation):
    a = choice(["a", "b"], "a")
    if mutation == "unknown":
        a["choice"] = "invented"
    elif mutation == "nan":
        a["probabilities"]["a"] = float("nan")
    elif mutation == "missing":
        del a["probabilities"]["b"]
    elif mutation == "negative":
        a["probabilities"]["b"] = -1
    elif mutation == "non_max":
        a["choice"] = "b"
    else:
        a["confidence"] = 5
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(a, {"a", "b"})


def test_one_index_per_node_with_operation_specific_targets():
    elements, targets, controls = model.action_space(page()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1"
    assert targets["CLICK"]["1"]["id"] == "e2"
    assert targets["CLICK"]["2"]["id"] == "e3"
    assert "WAIT" in controls


def test_all_heads_are_one_request_and_only_matching_head_executes(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "click_target": {"choice": "invented"},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert len(calls) == 1
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert set(calls[0]["questions"]) == {"operation", "click_target", "type_text_target"}


def test_click_cannot_consume_a_text_target(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "type_text_target": choice(["1"], "1"),
                "click_target": choice(["1", "2", "999"], "999"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


def test_target_head_receives_control_state_and_full_next_step_rules(monkeypatch):
    p = page()
    p["actions"].insert(0, {
        "id": "toggle", "kind": "click", "label": "Free cancellation", "node": 30,
        "role": "checkbox", "checked": "true", "selected": False,
    })

    def post(_url, _key, body):
        questions = body["questions"]
        target = questions["click_target"]
        assert target["criteria"]["1"]["checked"] == "true"
        assert target["criteria"]["1"]["selected"] is False
        assert questions["operation"]["instructions"]["rules"] in target["instructions"]["rules"]
        return {
            "model": "test",
            "answers": {
                "operation": choice(questions["operation"]["criteria"], "CLICK"),
                "click_target": choice(target["criteria"], "3"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Search with free cancellation", [])
    assert d["choice"] == "e3"


def test_quoted_task_text_still_uses_the_llm(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.field_context('Fly from "Zurich" to London', page()["actions"][0], page(), [])
    assert model.field_text(context)[0] == "Zurich"
    assert post.call_count == 1
    sent = json.loads(post.call_args.args[2]["messages"][1]["content"])
    assert sent["goal"] == 'Fly from "Zurich" to London'


def test_missing_text_credential_stops_before_guessing(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        model.field_text({"goal": 'Enter "Zurich"'})


@pytest.fixture
def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.screenshots = False
    a.pending_text = None
    a.success_check = None
    p = page()
    a.state = {
        "browser": Mock(fresh=Mock(return_value=True), observe=Mock(return_value=p)),
        "page": p,
        "decision": decision(),
        "goal": "Find a book",
        "history": [],
        "decisions": [],
        "status": "predicted",
        "started_at": time.perf_counter(),
        "record": False,
        "text_calls": [],
        "done_rejections": 0,
        "done_reject": None,
    }
    return a


def test_stale_decision_is_consumed_before_any_mutation(runner):
    runner.state["browser"].fresh.return_value = False
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["decision"] is None


def test_generated_text_reused_only_for_identical_retry_context(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 1
    assert runner.state["browser"].act.call_count == 2  # The first call rejects before any browser input.
    assert runner.pending_text is None


def test_changed_field_context_does_not_reuse_generated_text(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["page"]["text"] = "Different page context"
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 2


def test_loading_waits_do_not_trigger_no_progress_stop(runner):
    for _ in range(5):
        runner.state["decision"] = decision("wait")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert len(runner.state["history"]) == 5 and runner.state["status"] == "ready"


def test_stale_observation_preserves_executed_action(runner):
    runner.state["decision"] = decision("e3")
    runner.state["browser"].observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["action"] == "Go"
    runner.state["browser"].act.assert_called_once()


def test_observation_is_one_atomic_browser_read(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp = Mock(return_value={"result": {"value": p}})
    monkeypatch.setattr(browser, "cdp", cdp)
    actual = browser_operation({"operation": "observe", "session": "test", "screenshot": False})
    assert actual["actions"] == p["actions"]
    assert cdp.call_count == 1
    assert cdp.call_args.args[0] == "Runtime.evaluate"


def test_executor_rejects_a_stale_page_before_browser_input(monkeypatch):
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=False)
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    with pytest.raises(StalePage):
        b.act(page()["actions"][0], page(), "book")
    operation.assert_not_called()


@pytest.mark.parametrize("response", [{"exceptionDetails": {}}, {"result": {}}])
def test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(monkeypatch, response):
    import jev_ultrafast.browser as browser

    # A navigation can destroy the evaluation result after the change event already fired.
    if "exceptionDetails" in response:
        response["exceptionDetails"] = {"text": "Execution context destroyed"}
    cdp = Mock(return_value=response)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="Dropdown execution"):
        browser_operation({"operation": "act", "session": "test", "action": {
            "id": "e1", "kind": "select", "node": 1, "value": "Design",
        }})
    assert cdp.call_count == 1


def test_fingerprint_tracks_values_and_identity_not_screenshots():
    p = page()
    other = deepcopy(p)
    other["screenshot"] = "changed"
    assert fingerprint(p) == fingerprint(other)
    other["actions"][0]["node"] = 99
    assert fingerprint(p) != fingerprint(other)


@pytest.mark.parametrize("changed", ["Departure", "Where from?", "Where to?", "year"])
def test_flight_verification_rejects_wrong_trip(changed):
    from examples.flights import verify

    actual = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": "Track prices from Zürich to London departing 2026-09-20",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", "London"),
                ("Departure", "Sun, Sep 20"),
                ("Nonstop flight on Sunday, September 20. Select flight", ""),
            ]
        ],
    }
    assert verify(actual)["passed"]
    if changed == "year":
        actual["text"] = actual["text"].replace("2026", "2027")
    else:
        next(a for a in actual["actions"] if a["label"] == changed)["value"] = "wrong"
    assert not verify(actual)["passed"]


@pytest.mark.parametrize(
    "content", ["Thinking: Zurich", '{"text":null}', '{"text":"Zurich","extra":true}', '{"text":123}']
)
def test_text_helper_rejects_invalid_values(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Find a flight"})


def blocked_decision(operation_probabilities):
    return {
        "choice": "BLOCKED",
        "operation": "BLOCKED",
        "target": None,
        "confidence": 0.9,
        "probabilities": {"BLOCKED": 0.9},
        "operation_probabilities": operation_probabilities,
        "latency_ms": 10,
        "usage": {},
    }


def test_blocked_scrolls_when_more_page_is_below(runner):
    p = runner.state["page"]
    p["actions"].insert(-1, {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560})
    runner.state["decision"] = blocked_decision({"BLOCKED": 0.9, "CLICK": 0.1})
    runner.command("act", {"fingerprint": p["fingerprint"]})
    assert runner.state["browser"].act.call_args.args[0]["id"] == "scroll_down"
    assert runner.state["status"] == "ready"
    assert runner.state["history"][-1]["operation"] == "BLOCKED->SCROLL_DOWN"
    assert runner.state["history"][-1]["probability"] == 0.9


def test_blocked_without_scroll_stops_with_reason(runner):
    runner.state["decision"] = blocked_decision({"BLOCKED": 0.8, "CLICK": 0.15, "WAIT": 0.05})
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["status"] == "blocked"
    assert "4 observed actions" in runner.state["blocked_reason"]
    assert "BLOCKED 0.80" in runner.state["blocked_reason"]


def test_no_progress_rule_sets_reason(runner):
    for _ in range(3):
        runner.state["decision"] = decision("e3")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "blocked"
    assert "unchanged" in runner.state["blocked_reason"]
    assert "Loop:" in runner.state["blocked_reason"]  # same target 3x is named for the caller


def done_decision():
    return {**decision(), "choice": "DONE", "operation": "DONE"}


def test_done_rejected_by_success_check_is_retold_to_the_model(runner):
    runner.success_check = "window.ok === true"
    runner.state["browser"].evaluate.return_value = False
    runner.state["goal"] = "Find a book"
    runner.state["decision"] = done_decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].evaluate.assert_called_once_with("window.ok === true")
    runner.state["browser"].act.assert_not_called()
    assert runner.state["status"] != "done"
    assert any("DONE rejected" in note for note in runner.notes())


def test_done_accepted_when_success_check_is_true(runner):
    runner.success_check = "true"
    runner.state["browser"].evaluate.return_value = True
    runner.state["decision"] = done_decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "done"


def test_write_goal_without_fill_or_select_rejects_done(runner):
    runner.state["goal"] = "Add a project"
    runner.state["history"] = [{"kind": "click", "action": "Go", "page_changed": True}]
    runner.state["decision"] = done_decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "ready"
    assert any("DONE rejected" in note for note in runner.notes())


def test_write_goal_with_a_fill_accepts_done(runner):
    runner.state["goal"] = "Add a project"
    runner.state["history"] = [
        {"kind": "fill", "action": "Name", "page_changed": True},
        {"kind": "click", "action": "Go", "page_changed": True},
    ]
    runner.state["decision"] = done_decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "done"


def test_three_rejected_dones_stop_for_an_adjusted_goal(runner):
    runner.success_check = "false"
    runner.state["browser"].evaluate.return_value = False
    for _ in range(3):
        runner.state["decision"] = done_decision()
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["status"] == "blocked" and runner.state["next_step"] == "adjust"
    assert "DONE was rejected 3 times" in runner.state["blocked_reason"]


def test_three_same_labels_stop_even_when_the_page_changes(runner):
    runner.state["browser"].observe.side_effect = [dict(page(), fingerprint=f"after-{i}") for i in range(3)]
    for _ in range(3):
        runner.state["decision"] = decision("e3")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert [h["page_changed"] for h in runner.state["history"]] == [True, True, True]
    assert runner.state["status"] == "blocked" and runner.state["next_step"] == "adjust"
    assert "ran three times" in runner.state["blocked_reason"]


def test_three_scrolls_with_changing_page_are_progress(runner):
    scroll = {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560}

    def scrolled(i):
        p = dict(page(), fingerprint=f"after-{i}", actions=[*page()["actions"][:-1], scroll, page()["actions"][-1]])
        return p

    runner.state["browser"].observe.side_effect = [scrolled(i) for i in range(3)]
    runner.state["page"] = scrolled("start")
    for _ in range(3):
        runner.state["decision"] = decision("scroll_down")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "ready"
    assert [h["kind"] for h in runner.state["history"]] == ["scroll"] * 3


def test_success_check_error_is_a_rejection(runner):
    runner.success_check = "slow()"
    runner.state["browser"].evaluate.side_effect = TimeoutError("IPC response timed out")
    runner.state["decision"] = done_decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "ready"
    assert any("DONE rejected" in note and "timed out" in note for note in runner.notes())


def test_three_different_labels_with_changing_page_keep_going(runner, monkeypatch):
    monkeypatch.setattr(loop, "field_text", Mock(return_value=("x", {"model": "stub", "latency_ms": 1})))
    runner.state["browser"].observe.side_effect = [dict(page(), fingerprint=f"after-{i}") for i in range(3)]
    for choice_id in ["e1", "e2", "e3"]:
        runner.state["decision"] = decision(choice_id)
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "ready"


def test_evaluate_waits_for_promises(monkeypatch):
    cdp = Mock(return_value={"result": {"value": True}})
    monkeypatch.setattr(browser_mod, "cdp", cdp)
    b = browser_mod.Browser.__new__(browser_mod.Browser)
    b.session = "s"
    assert b.evaluate("fetch('/x').then(r => r.ok)") is True
    assert cdp.call_args.kwargs["awaitPromise"] is True


def test_step_budget_is_a_soft_stop_with_advice(runner, monkeypatch):
    monkeypatch.setattr(loop, "MAX_STEPS", 1)
    runner.state["decision"] = decision("e3")
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["decision"] = decision("e3")
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_called_once()  # The second choice is never executed.
    assert runner.state["status"] == "blocked" and runner.state["next_step"] == "adjust"
    assert "1-action budget" in runner.state["blocked_reason"]
    assert "Last steps:" in runner.state["blocked_reason"] and "Next: adjust" in runner.state["blocked_reason"]



@pytest.mark.parametrize(
    ("error", "next_step"),
    [
        (model.ModelError("Model provider returned HTTP 503", True), "retry"),
        (model.ModelError("Model provider returned HTTP 413", False), "adjust"),
        (RuntimeError("Dropdown execution was interrupted; inspect before retrying."), "adjust"),
        (model.ModelError("TYPESAFE_API_KEY is not set", False), "adjust"),
    ],
)
def test_tick_turns_failures_into_a_stop_with_next_step(runner, monkeypatch, error, next_step):
    monkeypatch.setattr(loop, "choose", Mock(side_effect=error))
    runner.state["status"] = "ready"
    runner.command("tick")
    runner.state["browser"].act.assert_not_called()
    assert runner.state["status"] == "blocked" and runner.state["next_step"] == next_step
    assert f"Next: {next_step}" in runner.state["blocked_reason"]


def test_tick_lets_programming_errors_surface(runner, monkeypatch):
    monkeypatch.setattr(loop, "choose", Mock(side_effect=KeyError("typo")))
    runner.state["status"] = "ready"
    with pytest.raises(KeyError):
        runner.command("tick")


def test_unobserved_mutation_is_never_marked_retry(runner, monkeypatch):
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("e3")))
    runner.state["status"] = "ready"
    runner.state["browser"].observe.side_effect = StalePage("Page did not settle after 10 observations.")
    runner.command("tick")
    runner.state["browser"].act.assert_called_once()
    assert runner.state["history"][-1]["page_changed"] is None
    assert runner.state["next_step"] == "adjust" and "not observed" in runner.state["blocked_reason"]


def test_interrupted_dropdown_is_logged_as_unconfirmed(runner, monkeypatch):
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("e3")))
    runner.state["status"] = "ready"
    runner.state["browser"].act.side_effect = RuntimeError("Dropdown execution was interrupted")
    runner.command("tick")
    assert runner.state["history"][-1]["unconfirmed"] is True
    assert runner.state["next_step"] == "adjust"


def test_missing_goal_value_is_not_retryable(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    reply = {"choices": [{"message": {"content": '{"text": null}'}}]}
    monkeypatch.setattr(model, "post_json", Mock(return_value=reply))
    with pytest.raises(model.ModelError, match="Add the value") as caught:
        model.field_text({"goal": "Fill the form"})
    assert caught.value.retry is False


def test_tick_stops_when_the_page_never_settles(runner):
    runner.state["browser"].fresh.side_effect = StalePage("navigating")
    runner.state["browser"].observe.side_effect = StalePage("Page did not settle after 10 observations.")
    runner.command("tick")
    assert runner.state["next_step"] == "retry" and "did not settle" in runner.state["blocked_reason"]


def test_notes_warn_before_hard_limits(runner, monkeypatch):
    monkeypatch.setattr(loop, "MAX_STEPS", 20)
    p = runner.state["page"]
    p.update(omitted_actions=7, text_truncated=True)
    step = {"action": "Go", "kind": "click", "operation": "CLICK", "page_changed": False}
    runner.state["history"] = [dict(step) for _ in range(16)]
    runner.state["history"][-1].update(role="combobox", settled=False)
    notes = " | ".join(runner.notes())
    for expected in ("7 more controls", "cut at 6000", "6 earlier actions", "'Go' was chosen 8 times",
                     "last 2 actions did not change", "No suggestion list", "4 actions left"):
        assert expected in notes
    runner.state["history"], p["omitted_actions"], p["text_truncated"] = [], 0, False
    assert runner.notes() == []


def test_notes_reach_the_model_only_when_present(monkeypatch):
    bodies = []

    def post(url, key, body):
        bodies.append(body)
        return {"answers": {"operation": choice(["CLICK", "TYPE_TEXT", "WAIT", "DONE", "BLOCKED"], "DONE")},
                "model": "test"}

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    model.choose(page(), "Find a book", [])
    model.choose(page(), "Find a book", [], ["4 actions left before the run stops."])
    assert "notes" not in bodies[0]["state"]
    assert list(bodies[1]["state"])[0] == "notes"  # Laya cuts a dict state from the end.
    assert bodies[1]["state"]["notes"] == ["4 actions left before the run stops."]


@pytest.mark.parametrize(("code", "retry", "hint"), [(413, False, "LAYA_TOURNAMENT_GROUP"), (503, True, "Wait")])
def test_provider_errors_carry_retry_flag_and_hint(monkeypatch, code, retry, hint):
    import httpx

    monkeypatch.setattr(model, "CLIENT", Mock(post=Mock(return_value=httpx.Response(code, text="too many"))))
    monkeypatch.setattr(model.time, "sleep", Mock())
    with pytest.raises(model.ModelError) as caught:
        model.post_json("http://laya.test", "key", {})
    assert caught.value.retry is retry and hint in str(caught.value) and "too many" in str(caught.value)


def test_text_helper_names_token_cutoff(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    cut = {"choices": [{"message": {"content": '{"text": "Zur'}, "finish_reason": "length"}]}
    monkeypatch.setattr(model, "post_json", Mock(return_value=cut))
    with pytest.raises(model.ModelError, match="cut at 1024 tokens"):
        model.field_text({"goal": "Find a flight"})


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1280x2000", (1280, 2000)), (None, (1120, 780))],
)
def test_viewport_env_parses_size(monkeypatch, value, expected):
    import jev_ultrafast.browser as browser

    if value is None:
        monkeypatch.delenv("JEV_VIEWPORT", raising=False)
    else:
        monkeypatch.setenv("JEV_VIEWPORT", value)
    assert browser.viewport_size() == expected


def test_viewport_env_rejects_bad_value(monkeypatch):
    import jev_ultrafast.browser as browser

    monkeypatch.setenv("JEV_VIEWPORT", "bad")
    with pytest.raises(ValueError, match="JEV_VIEWPORT must be WIDTHxHEIGHT"):
        browser.viewport_size()


def test_navigation_during_prediction_reobserves_without_action(runner):
    runner.state["browser"].fresh.side_effect = StalePage("Document navigating")
    runner.command("tick")
    assert runner.state["status"] == "ready"
    assert runner.state["decision"] is None
    runner.state["browser"].act.assert_not_called()
