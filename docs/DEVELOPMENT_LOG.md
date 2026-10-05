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
- The correction at `c8e4f51` passed all five jobs in
  [run 37259569652](https://github.com/tyama-ds/agent-workbench/actions/runs/37259569652).
  Actual desktop, tablet and narrow screenshots were inspected; controls are reachable
  without sidebar/workspace overlap. Later commits must retain their own green checks.
- Local suite: 278 passed, 4 Windows-only skips. Full screen-reader/text-zoom audits and
  pixel-baseline comparison remain outside this cycle's evidence.

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

## Cycle 2 — truthful assignment and recovery v1 (2026-10-05)

Application version **0.1.1.dev2**, based on cycle 1 head
`8bf4cb830aef9675a1f902c39ba558dbe453108b`. Retains the same cockpit and scheduler.

### Adopted

- Expose the actual initial PM/worker brief as a distinct `assignment` string, redacted
  by the existing snapshot boundary. Display and search this field. Replies and peer
  messages remain conversation entries; they do not silently replace the original brief.
  Never expose the internal asyncio `task`, pending queue, conversation or configuration.
- Derive `status_reason` from runtime state: human questions, unfinished teammates,
  teammate errors, failed runs, collaboration blocking and mixed attention. Generic
  waiting no longer claims the human owes an answer. Stopped agents with an old question
  are not counted as current human questions. No generated progress percentages.
- Derive PM identity from the actual parent relationship, not a model-provided role name.
  Queueing a human follow-up during inference retains the agent's working state.
- Expose read-only `message_eligibility` with `allowed`, `reason` and explanatory `message`.
  The POST rechecks the same predicate before changing queues/questions/errors/status.
  Stopping, stopped, stale settings, a full queue and exhausted turn/time/model/context
  budgets explain their recovery path. Stopping does not claim writes have finished.
- Preserve allowed human direction after automatic collaboration exhaustion; no budget
  resets. Exhausted tool calls still allow text-only model completion and show a warning.
  Admission is a current-state hint, not a reservation or promise of future model success.
- Extend contract, transition, frontend, DOM-only and real Edge tests. The real HTTP/engine
  browser phase checks assignment search, a human question, hard-turn recovery and stale
  configuration guidance. All inputs remain synthetic and no model endpoint is called.

### Research decisions

- [OpenTelemetry trace API](https://opentelemetry.io/docs/specs/otel/trace/api/): adopt the
  limited principle of explicit operation identity, parent relationships and evidence-based
  status. Reject a tracing SDK, exporter or collector: unnecessary for this in-memory UI.
- [Microsoft Human-AI Interaction guidelines](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf):
  adopt clear capability/state feedback and an actionable recovery explanation. Reject
  inferred completion/progress from model prose and automatic retries that consume budget.
- Defer assignment revision/history, persisted activity, broad state-machine changes,
  new providers, approval flows and telemetry to separate reviewed cycles.

### Screenshot-led correction

The first cycle 2 Edge run passed its assertions, but pixel inspection exposed a stale
send confirmation carried into a newly selected run. Clear composer feedback on run or
automatic agent selection, and bind late send success/error feedback to its original
selected agent. Preserve drafts and queue behavior. Add browser/DOM regression assertions;
the corrected source requires its own exact-head CI and screenshot review.

### Verification

Final exact-head CI and screenshot evidence is recorded in the cycle handoff. Historical
cycle 1 browser evidence above remains tied to its named commits and is not reused as
proof for this cycle's changes.
