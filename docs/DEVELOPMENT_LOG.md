# Versioned development log

## Cycle 1 — browser acceptance v1 (2026-10-05)

Based on PR #1 head `9067567388d659b4d00109f0d5cb3ecc7b5e7f71`.
Application version stays 0.1.0: this cycle changes validation, not shipped behavior.
The test-only package is version 0.1.1 and the assertion report schema is version 1.

### Adopted

- Run genuine Edge browser acceptance on Windows CI, with a lockfile-pinned test-only
  Playwright driver. No Node/Playwright requirement is added to Windows setup or the app.
- Preserve real bootstrap, cookie session, settings persistence, memory-only secret and
  local models-list checks; label synthetic content and reject off-origin browser requests.
- Retain a controlled UI-state phase for race/draft/limit/XSS checks, correcting its run
  status and rejecting agent fields outside the actual `Agent.public()` contract.
- Add a separate real HTTP/Engine phase with a deterministic injected model client. It
  creates a worker, emits completion mail, asks the human, accepts a reply and is cancelled
  through real endpoints. No LLM endpoint or paid inference is involved.
- Check 1366×768 and 390×844, native-dialog keyboard focus/Escape/restoration, polling
  focus, per-agent drafts, overflow, settings locks and unlocks. Upload only synthetic
  screenshots and JSON assertions, including failure evidence, for 14 days.

### Research decisions

- [W3C modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/): adopt
  focus containment, Escape and return-focus checks; do not replace native dialogs.
- [VS Code accessibility](https://code.visualstudio.com/docs/configure/accessibility/accessibility):
  adopt keyboard/state observability and reduced-motion test context; defer a complete
  screen-reader audit rather than equating a browser smoke with accessibility certification.
- [Playwright screenshot guidance](https://playwright.dev/docs/test-snapshots): pair images
  with explicit state assertions and record browser version. Defer pixel baselines until
  a stable browser/font runner is chosen; Edge on windows-latest is intentionally updated.
  Screenshots are review evidence, not automatically accepted pixel-regression baselines.
- Defer approval engine, persisted history and new providers to separate reviewed cycles.

### Known limits / next candidates

- Local browser launch is blocked by this executor's process/socket policy. CI must run
  before declaring browser validation passed; local Python checks alone are insufficient.
- Assignment display/search currently looks for a non-public `agent.task` field. The
  synthetic snapshots no longer mask that gap; a future distinct assignment field must
  not expose the internal asyncio task.
- Waiting status labels can conflate human questions with error/budget waiting. The real
  human-question filter is tested; broader state semantics are a separate change.
- No live model quality, target GPU behavior, company proxy or real user's desktop is tested.
