
## 2026-11-05 — orchestrator: RUN jev-fix (report csc s2) start HEAD 83c828e (dirty tree), tier Full, ponytail full
ITEM 1 PLANNED p1-fix: success_check + empty-DONE fallback (agent.py, examples/run.py, browser.py evaluate awaitPromise)
ITEM 2 PLANNED p1-fix: hard stop on same label 3x in a row (agent.py)
ITEM 3 PLANNED p1-fix: TARGET rule no re-click current page nav (questions.py)
ITEM 4 PLANNED p1-fix: PYTHONUNBUFFERED=1 in SKILL.md run cmd. CDP timeout SKIPPED: helpers.py:42 already 5 s.
ITEM 5 PLANNED p1-fix: evaluate awaitPromise=True (browser.py:56-60)
LIVE reruns on csc prod (creates a deal) + hosted-model compare = remote write/paid -> need user yes.
Expected: DONE with check false -> not done, note "DONE rejected"; 3 rejected DONE -> blocked adjust; 3 same non-wait label in row -> blocked adjust even if page_changed True.

## 11:33 — p1-fix: P1-FIX REPORT
- agent.py: success_check kwarg, done_rejection(), DONE gate, 3-strike stop, same-label stop, DONE note in notes(). Tests a-f added in tests/test_agent.py; 60 pass.
- browser.py evaluate awaitPromise=True. questions.py TARGET line. SKILL.md PYTHONUNBUFFERED=1. run.py --success-check.
- Decisions A-euc4qa@1, A-wkphwc@1 in sp, limits.md, DECISIONS.md.
- Gates: owned-file ruff pass; full ruff 1177 errors all in vendored laya/; pytest 60 pass; node ok; uv build ok.
- Mistake: /tmp/x created by git show. Not deleted.
- Open: same-label false stop (shortcut in code); no live run.
## 2026-11-05 11:34 — orchestrator: p1-fix round1 snapshot c8721244; pytest 60 pass, ruff on jev_ultrafast/tests/examples/scripts clean; ruff . fails only in nested laya/ repo (not this change); dist/ ignored. Codex review started.
## 2026-11-05 11:38 — orchestrator: Codex r1: P1 scroll repeats false-stop (valid, agent.py:300); P2 direct predict/act error conversion = pre-existing dirty-tree work, out of scope. Own: success_check TimeoutError (>5s IPC) escapes tick (agent.py:124-128). ITEM1,2 SENT BACK r1.

## 11:38 — p1-fix: P1-FIX ROUND 2 REPORT
- Fix 1: same-label rule excludes kind wait and scroll (agent.py ~302). Test: test_three_scrolls_with_changing_page_are_progress -> ready.
- Fix 2: done_rejection catches StalePage, TimeoutError, RuntimeError as a rejection (agent.py ~127). Test: test_success_check_error_is_a_rejection -> DONE rejected, ready.
- Limits row A-wkphwc and A-euc4qa updated to match.
- Gates: pytest 62 pass; owned ruff clean; node ok; uv build ok. Full-repo ruff errors remain in vendored laya/ (pre-existing).
- Direct predict/act error path untouched (out of scope).
- Open: /tmp/x from round 1 still exists; rm proposed, not run.
## 2026-11-05 11:39 — orchestrator: r2 diff ok; pytest 62 pass, ruff clean on jev code, node ok, build ok. Codex r2 started.
## 2026-11-05 11:42 — orchestrator: Codex r2 clean. ITEMS 1-5 ACCEPTED. Live rerun NOT DONE (needs user yes: prod write + paid hosted model).
