# Versioned development log

## Cycle 1 — browser acceptance v1 (2026-10-05)

Based on PR #1 head `9067567388d659b4d00109f0d5cb3ecc7b5e7f71`.
Application version is 0.1.1.dev1: browser evidence uncovered a narrow-layout defect,
so this cycle also includes a targeted responsive preservation fix.
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

### Responsive correction discovered by actual pixels

The first fully passing browser run on head `5b4104c` was
[run 37259217044](https://github.com/tyama-ds/agent-workbench/actions/runs/37259217044).
Independent screenshot review still found overlap after the stop notice at 390px.
A more-specific notice selector retained a viewport-fixed shell height on stacked layouts.

- Match that selector in the responsive auto-height override.
- Keep narrow rails/content in natural document flow, with bounded internally scrolling
  cards/logs, so long Japanese questions and the send form remain reachable.
- Add vertical region/control bounds assertions, active long-question and 820px tablet
  screenshots, plus reset the scrollable settings dialog before its screenshot.
- Desktop structure, colors, interaction and model/security behavior are preserved.
- A new exact-head CI run and independent pixel review are required for this correction;
  the earlier green run does not validate it.

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

- Local browser launch is blocked by this executor's process/socket policy. Windows CI
  has now run the real browser; each correction still needs its own exact-head rerun.
- Assignment display/search currently looks for a non-public `agent.task` field. The
  synthetic snapshots no longer mask that gap; a future distinct assignment field must
  not expose the internal asyncio task.
- Waiting status labels can conflate human questions with error/budget waiting. The real
  human-question filter is tested; broader state semantics are a separate change.
- No live model quality, target GPU behavior, company proxy or real user's desktop is tested.
