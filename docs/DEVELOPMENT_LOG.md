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
the corrected source requires its own exact-head CI and screenshot review. A second
review clarified that the collaboration limit alone does not stop existing work; the
notice must not imply a stopped team can resume. Explicit stopped-team copy and a browser
assertion cover the combined stopped/limit state.

### Verification

Final exact-head CI and screenshot evidence is recorded in the cycle handoff. Historical
cycle 1 browser evidence above remains tied to its named commits and is not reused as
proof for this cycle's changes.

## Cycle 3 — Current-session results and save receipts (0.1.1.dev3)

### Implemented scope

- Keep terminal no-tool assistant responses separate from explicit `finish_work` reports.
  Both are model-authored text, not factual verification. Intermediate narration,
  questions, cancelled turns and errors do not become terminal responses.
- Keep the latest 20 reports (24,000 characters each) and 64 actual file-save receipts
  per agent, separately from the existing 200 log entries. Show retention omissions
  and text truncation explicitly. Records remain in memory for this server session.
- Save receipts come only from successful text/Office tool operations and include the
  actual path, saved byte count, SHA-256, tool, agent/turn, timestamp and create/update
  mode from the validated preimage. The completion observer runs on the event loop,
  including successful writes drained during Stop. Receipt observer failure cannot
  turn a committed save into an apparent save failure.
- A saved hash identifies bytes at save time, not the current path contents or factual
  correctness. No file existence/readability/download promise and no new filesystem
  route. Write-only scope remains write-only. Resume makes prior responses historical.
- Copy/export is an explicit action on selected redacted public text/receipt metadata.
  Exports are plain UTF-8 text, with no hidden reasoning, provider protocol, settings,
  automatic persistence, backups or telemetry. Async clipboard feedback is selection-
  and request-scoped. No Office bytes are copied or downloaded by this feature.

### Research decisions

[W3C PROV-DM](https://www.w3.org/TR/2013/REC-prov-dm-20130430/): adopt the small relationship
between output identity, producing activity and responsible agent. Provenance informs
trust assessment; it does not certify content. Record create/update from successful
operations and preserve save-time hashes. Defer RDF/PROV serialization and source graphs.

Defer file retrieval: a later feature needs opaque receipt IDs, fresh allowed-read and
path/link checks plus hash validation of the exact bytes returned, with changed,
missing and inaccessible states distinguished. Reject arbitrary filesystem path routes,
model-inferred file receipts, automatic archives and persistent history.

### Verification

Final tests, exact-head Windows/Edge CI and screenshot review are recorded in the cycle
handoff. Earlier cycle evidence does not prove this feature's implementation.

### Windows path normalization correction

The first Edge run reached real result export and path copy, then exposed a test-only
assumption: Windows temporary paths may use an 8.3 user-directory alias while the path
guard returns the canonical long path. Compare the copied path with native realpath;
keep exact path verification and leave production permission/receipt behavior unchanged.

## 0.1.1.dev4 — Local preflight and honest provider evidence (2026-10-05)

- Added local-only run admission preview reusing start admission, with potential model/proxy/Web destinations and independent canonical read/write roots plus overriding automatic/app-state exclusions. Empty scope remains usable for text-only tasks; unused worker profiles do not block PM-only work.
- Kept configuration validity, app connectivity, model-list response, inference, and structured tool execution as distinct evidence. Header says Workbench / LOCAL APP. Explicit per-profile list checks are bounded and safely typed; no automatic discovery, inference, paid tests, capability guessing, or credential-persistence change.
- Kept the existing cockpit, results/copy/export, runtime status/reply contract, and task drafts. Preview and diagnostic feedback is invalidated on relevant edits, newer requests, and modal dismissal.

Primary-source research and decisions:
- [LM Studio tool support](https://lmstudio.ai/docs/developer/openai-compat/tools): native support combines model/template and server parsing; default support also exists with varying quality. Adopt uncertainty and structured-call-only execution; reject model-name allowlists and executing raw text as tools.
- [LM Studio models](https://lmstudio.ai/docs/developer/openai-compat/models): JIT can list downloaded rather than loaded models. Do not label listed models as loaded or ready.
- [OpenAI model listing](https://developers.openai.com/api/reference/resources/models/methods/list) and [Claude model listing](https://platform.claude.com/docs/en/api/models/list): list metadata is not an inference test; Claude is paginated. Preserve incomplete-list uncertainty and manual aliases.
- [Open WebUI compatible-provider setup](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/) explains that a failing models endpoint need not mean incompatible inference. Adopt manual IDs and protocol clarity; do not add protocol adapters in this cycle.
- [Open WebUI connection troubleshooting](https://docs.openwebui.com/troubleshooting/connection-error/) explains slow/unreachable endpoints blocking list loading. Keep checks explicit per profile, bounded, and separate from local admission.
- [Microsoft HAX G1](https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-what-the-system-can-do/) and [G2](https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-how-well-the-system-can-do-what-it-can-do/): separately explain scope and confidence. Adopt a compact task-dialog preview rather than a new onboarding wizard.
- Defer explicit optional inference/tool probes, automatic model loading/downloading, provider expansion, and persistent capability scores. Reject silent cloud fallback, network scanning, credential logging, and TLS/proxy bypasses.

Cycle-4 review correction: actual Edge testing found that native textarea change-on-blur could rebuild the preview and swallow a Start click. Deduplicating the effective preview request and retaining existing content avoids this layout mutation; expanded scope survives legitimate refreshes. Pointer/keyboard and delayed-response regression coverage is retained.

## 0.1.1.dev5 — Experimental Python-bundled Windows ONEDIR (2026-10-05)

- Preserve the source `Setup.cmd` / `Launch.cmd` route, existing cockpit, preflight,
  results and privacy behavior. Add an optional unsigned Windows x64 console build,
  built in a fresh CPython 3.13 environment using separate hash-locked build tools.
- Frozen normal launch runs the server in-process under the existing duplicate-launch
  mutex. Bundled resources and outer installation directory are independently protected
  from agent file access, alongside the state directory. State stays in LOCALAPPDATA.
- Fixed utility helpers isolate Windows DLL-search cleanup from concurrent server
  imports. They accept no arbitrary commands, use bounded pipes and timeouts, and place
  native descendants in a kill-on-close Job. Cancellation finishes acquiring the helper
  handle before killing/reaping it. Browser launch validates the exact loopback bootstrap
  URL and uses the Windows association, ignoring BROWSER command templates.
- Build output includes source/runtime/tool identity, dependency and native notices,
  per-file hashes, and ZIP checksum. Native redistribution review later blocked all
  binary uploads (see decision below); a packaging command is not release evidence.
- Independent early review caught inherited BROWSER command templates and sanitization
  after changing directory. Both were corrected, and browser startup now runs inside
  server cleanup protection. Unit regressions cover those boundaries.

Research decisions:
- [PyInstaller operating model](https://pyinstaller.org/en/stable/operating-mode.html):
  adopt inspectable ONEDIR with bundled Python and native Windows builds; defer one-file,
  MSIX, installers, automatic updates and additional architecture support.
- [PyInstaller runtime information](https://pyinstaller.org/en/stable/runtime-information.html):
  distinguish `_internal` resources from outer EXE location and avoid interpreting
  frozen `sys.executable` as a Python interpreter.
- [PyInstaller external-program guidance](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html):
  isolate DLL-search reset in short-lived helper processes rather than race global
  state against background work. Browser helpers intentionally do not own the browser
  in a kill-on-close Job.
- [PyInstaller license exception](https://pyinstaller.org/en/stable/license.html) and
  [CPython licensing](https://docs.python.org/3/license.html): retain actual interpreter,
  wheel and native-library notices; inventory the distribution rather than assuming
  a freezer removes dependency obligations.
- [Microsoft app reputation guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation):
  Python-free startup does not establish company approval or universal compatibility.
  Reject warning bypasses, self-signed trust changes and claims of unrestricted use.

No live model service, user data, user PC or corporate security configuration is used
for acceptance. Final exact-head CI, ZIP inspection and screenshots are recorded in
handoff; until those pass, the portable binary remains unverified.

First Windows build correction: Git's automatic CRLF conversion changed the exact
bytes of checksum-pinned third-party notice supplements. Mark those reviewed files
as binary-preserved in `.gitattributes`; do not weaken or normalize away their hash
checks. The full source/install/Edge suite passed before the packaging gate caught
this issue. Binary upload remains separately blocked on native redistribution review.

Redistribution decision: actual Windows lxml wheel and matching build configuration
indicate static iconv inclusion. Exact corresponding-source/relink obligations are
not established. The setup-python CPython LICENSE also lacks expected native
component labels, so interpreter dependency notices need build-specific review.
Stop expanding legal packaging in this cycle: require an explicit evaluation-only
build, inventory available notices and unresolved components honestly, retain exact
hashes, and remove binary artifact upload entirely. Only internal execution tests,
reports/screenshots and non-binary manifests may proceed. No source-offer commitment
or distribution clearance is made.
