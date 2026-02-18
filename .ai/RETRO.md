# Retrospective: OpenClaw TUI Dashboard

**Tier:** Standard | **Appetite:** 2-3h | **Actual:** ~45 min (design+build+integrate)

## What Worked

- **Parallel builders were fast.** Both Sonnet workers finished in 3-8 min. Total build time was dominated by the longer one (~8 min).
- **Spike saved us from a dead end.** `sessions_tree` doesn't exist and `sessions_history` is broken via HTTP. Found this in 30 seconds instead of building against a phantom API.
- **Self-contained work unit specs paid off.** Both builders produced code that integrated with only one fix needed (the test_app.py sys.modules pollution).
- **Making fields defensive (`.get()` with defaults) was critical.** Real gateway data has missing `abortedLastRun` fields on some sessions — strict parsing silently dropped 6/11 sessions.

## What Didn't Work

- **WU-2 builder injected mocks into `sys.modules` at import time**, poisoning the entire test suite when run together. Classic cross-test contamination. Tests that worked in isolation (19/19) broke 30 others in the integrated suite. Fixed by switching to `monkeypatch.setattr`.
- **Builder reported 53/53 passing but some of those tests were actually importing mocked modules.** The builder's tests ran in isolation and the mocks didn't conflict, but in the full suite they did. Lesson: integration test suite run is essential.

## What to Remember

- **Always run the full test suite after integration**, not just individual builder test files. Cross-test pollution is the #1 integration issue with parallel builders.
- **Spike the actual API before designing.** The build guide said `sessions_tree` existed — it doesn't. Trust but verify.
- **Default-safe parsing is essential for real-world APIs.** Use `.get()` with sensible defaults for all optional fields. Don't trust that every field will be present.
- **Sonnet workers are worth it on tight timelines.** The cost savings of Tier 1 (MiniMax/GLM) aren't worth the retry risk when the appetite is 2-3 hours.

## Process Improvements

- Add a convention to work unit specs: "DO NOT use `sys.modules` hacking for test mocking — use `monkeypatch.setattr` or `unittest.mock.patch` instead."
- Consider adding an explicit "integration test" step in PLAN.md that runs the full suite, not just per-WU tests.
