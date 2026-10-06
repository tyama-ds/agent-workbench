# Versioned development log

Historical PR handoff evidence, source/run/artifact links and exact snapshot provenance
are available in the [verification evidence index](evidence/README.md). The current PR
overview keeps only the latest head’s checks; archived claims retain their original scope.

## 0.1.1.dev28 — Neutral input presence and direct owner navigation (2026-10-06)

- Add passive input marks to existing crew/question cards, per-team input-owner
  counts, and one explicit cross-team next-input action in the existing sidebar.
  Keep the cockpit and question mode; no third dashboard or draft collection.
- A nonempty input field, including whitespace, establishes only text presence.
  Pending, unknown and already accepted text can remain after navigation or edits.
  Use neutral `入力あり`, count owners rather than messages, exclude the task editor,
  and never infer unsent state, priority, forgotten intent or current send eligibility.
- Derive known owners from current run/member summaries; preserve exact existing
  strings. Missing owners are not navigated to or silently reassigned/deleted.
  Do not copy message content into cards, search, status metadata or storage.
- Traverse current session-list order and each team's declared member order,
  selecting the exact run/agent once. Preserve both roster searches and mode;
  keep blocked inputs visible without enabling Send. Explicit navigation focuses
  the enabled composer or existing owner heading. Same-owner activation does not
  churn selection/navigation epochs; delayed state never performs that focus move.
- Presence transitions update existing render signatures and a concise polite count.
  Same-presence character edits and unchanged polls do not rebuild cards or rewrite
  count/label/status nodes. Successful existing text clearing updates indicators
  immediately, before the following state request completes.
- Independent source review tightened modal isolation, presence-only DOM updates,
  known-member badges and immediate post-clear rendering. Place navigation before
  search to preserve the existing native search-to-first-card Tab route. Dedicated
  production callback tests cover these cases without changing receipt semantics.

Research decisions:
- [VS Code editing](https://code.visualstudio.com/docs/editing/codebasics#_save-auto-save):
  adopt contextual marks and aggregate counts. Backup/Hot Exit are separate
  capabilities; these marks do not promise storage or restoration.
- [Slack drafts](https://slack.com/help/articles/201457107-Send-and-read-messages)
  and [Teams release notes](https://support.microsoft.com/en-us/teams/platform/what-s-new-in-microsoft-teams):
  cross-conversation discovery is an established messaging pattern. Defer a full
  collection because this smaller feature closes the visibility gap without a
  new lifecycle/filtering surface. Product precedent is not comparative evidence
  proving this design's benefit.
- [Mixed-initiative principles](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/chi99horvitz.pdf)
  and [Human-AI Interaction Guidelines](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf):
  interpret uncertainty conservatively, expose a quiet affordance, and leave
  invocation to the user. Reject automatic reminders, reopening and resubmission.
- [W3C status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html),
  [focus order](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html) and
  [native buttons](https://www.w3.org/WAI/ARIA/apg/patterns/button/): textual marks,
  native activation, count-only announcements and nearby unavailable-control
  fallback, without interrupting typing or announcing message content.

Separate confirmed follow-on: the existing message callback accepts an
object-shaped HTTP 2xx response without requiring the endpoint's `{ok:true}`
receipt. Synthetic production-API/callback reproduction with `200 {}` clears an
unchanged input and displays success. Strict receipt validation is not changed
in this discovery feature; no new accepted-status badge or attempt-state store
is introduced. This remains a distinct correction with its own outcome tests.

Verification uses deterministic production callbacks and the existing synthetic
Windows Edge route at desktop/tablet/narrow widths with 20 retained teams.
Exact-head full local/CI checks, artifact identity, independent source and actual
pixel review are required; earlier screenshots do not accept this revision.
Preserve the preceding dev27 public overview byte-for-byte in historical evidence.
No new endpoint, persistent storage, live inference, local browser retry, user-PC
action, dependency, bundled Python, merge, deployment or release is included.

Hosted acceptance correction:
- The [first exact source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37405818118)
  on `40bbfbce` passed all four matrix jobs. Edge reached the new desktop geometry
  check, then found a real focused-question-card clipping issue: the added sidebar
  controls and active notice left a roughly 222-pixel roster scrollport, smaller
  than the long question card. Independent failure-pixel review confirmed it.
- Keep the strict whole-target clipping assertion. Use concise card previews at
  every width, retaining full identity/question in selected detail and the separate
  team ID, neutral marker and two-line availability reason. Reserve a usable
  question scrollport and let a shorter sidebar scroll instead of hiding controls.
  Add measured clipping diagnostics and native focus coverage for blocked/unknown
  question cards as well as the allowed owner. Fresh exact-head hosted checks and
  actual pixels are required; the failed run does not accept the correction.
- The [second source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37406734628)
  on `15968d32` passed all four matrix jobs and the corrected desktop card checks,
  then the tablet test incorrectly expected a keyboard focus indicator after
  pointer selection followed by programmatic focus. Establish keyboard modality
  with a real Tab from the preceding control, retain the strict outline assertion,
  and include focus-visible diagnostics. Independent review also added actual
  enabled Next pointer clicks alongside Space at every viewport. No production
  focus-style workaround or relaxed clipping check is introduced; rerun the exact
  final source and inspect its artifacts before acceptance.
- The [third source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37407490083)
  on `d2ef8ea3` passed all four matrix jobs and reached narrow card visibility.
  After a direct programmatic card focus, its 240-pixel rectangle was partly
  outside the horizontal strip (left 259, right 499, viewport right 390), while
  vertical bounds and content overflow passed. Keep that measured evidence and
  the strict visibility assertion. Exercise actual search-to-card Tab traversal
  for each enabled/blocked/unknown target, without test-side scrolling, before
  inferring a native keyboard reveal defect or adding production scroll behavior.

## 0.1.1.dev27 — Displayed request text into a protected new-task draft (2026-10-06)

- Reproduced that selecting an older team did not bring its request into the new-task
  editor, while the editor could hold a different meaningful draft. Add one secondary
  action in the selected-team overview and reuse the existing dialog. Only public
  display-redacted request text is adopted; preserve current form choices and all
  agent drafts/navigation. No historical conversation, results, configuration,
  credentials, permissions or budget are copied.
- Protect every nonempty differing draft, including whitespace-only input, with
  explicit Keep/Replace. Identical content opens without draft-epoch churn. Pending
  choices block Start and suppress/invalidate preflight. Adoption or Keep uses the
  existing admission-only preflight; creating a team still needs explicit Start.
- Bind replacement to source ID/raw displayed text, selection/navigation/dialog/
  workspace/draft epochs and the actual current payload. Cancel stale/ABA choices,
  source removal/remasking and intervening edits. Preserve newer focus and feedback;
  guard pending start requests without changing their existing outcome semantics.
- Preserve text and literal redaction markers except native textarea CRLF/CR-to-LF
  normalization, disclosed in the dialog. Compare raw source for freshness, normalized
  text for editor equality and the 16,000 UTF-16-unit limit. Reject unavailable or
  oversized candidates without truncation; whitespace-only and NUL sources are also
  unavailable, matching backend task validation. This is displayed text, not byte-exact
  original data, verified latest state, resumed execution or restored authority.

Hosted acceptance correction:
- The [first source Edge run](https://github.com/tyama-ds/agent-workbench/actions/runs/37401350963)
  on `3559294` reached the new source-removal case but the synthetic compact response
  incorrectly claimed loaded detail after deleting its requested agent. The app
  correctly rejected that inconsistent response and retained its last displayed
  source. Independent review and the failure screenshot confirmed this. Keep strict
  compact validation; assert malformed-response retention, then test accepted removal
  through the explicitly supported legacy full-state fixture. The Engine itself does
  not delete retained runs during its lifetime. All four matrix jobs passed; fresh
  exact-head Edge/aggregate gates are required after this fixture correction.
- Source review also found that polling-driven invalidation left the old preflight
  guidance waiting for a decision that no longer existed. Resume admission-only
  checking of the retained current draft after cancellation, without adopting or
  executing anything; a focused regression verifies the exact preview payload.

- The [second source Edge run](https://github.com/tyama-ds/agent-workbench/actions/runs/37402154387)
  on `88db2ef` passed all matrix jobs and the corrected state cases, then exposed a
  real tablet keyboard-reading issue: End on an already bottom-scrolled preview
  scrolled its surrounding dialog, hiding the still-focused preview. Independent
  failure pixels confirmed it. Reset only a newly opened candidate's preview; keep
  unmodified Home/End inside that focused reading region and contain overscroll.
  Retain strict clipping checks and add repeated-End/Home cases; unchanged polls
  still preserve reading position. New exact-head hosted evidence is required.

Research decisions:
- [GitLab manual pipelines](https://docs.gitlab.com/ci/pipelines/#run-a-pipeline-manually):
  adopt editable preparation separated from an explicit execution action.
- [AWS Step Functions redrive](https://docs.aws.amazon.com/step-functions/latest/dg/redrive-executions.html):
  reject restart/resume semantics, which require preserved execution history and
  definition guarantees that this text-only feature does not provide.
- [Microsoft HAI guidelines](https://www.microsoft.com/en-us/research/uploads/prod/2019/03/AI_Guidelines_Poster_PrintQuality.pdf):
  apply efficient correction, cautious adaptation, short-term references and clear
  consequences through editable drafts and overwrite protection. This is design
  guidance, not a user study or proof of demand.
- [Slack draft discovery](https://slack.com/help/articles/201457107-Send-and-read-messages)
  and [VS Code unsaved editing](https://code.visualstudio.com/docs/editing/codebasics#_save-auto-save):
  a real alternative is finding hidden per-agent drafts. Defer a global draft view
  because nonempty task text can already have been submitted, and blocked/vanished
  owners and unknown send outcomes need separate contracts. Do not imply durable
  recovery, add storage or introduce another dashboard.

Coverage uses production callbacks with deferred transport, non-mutating Engine
preflight checks and Windows Edge native keyboard/layout cases. Exact-head full
local/CI gates, independent source review and actual screenshot inspection are
required before acceptance. Preserve previous verification bytes in the historical
evidence index. No local browser retry, live inference, user-PC action, dependency,
bundled binary, merge, deployment or release is included.


## 0.1.1.dev26 — all-session human questions (2026-10-06)

- Reproduce the visibility gap: the old header counted only the selected team's
  questions, while another running team could contain a paused agent. Reuse the
  existing roster for an explicit global question view; retain the cockpit and
  clearly identify the selected team's center/right context.
- Show independent membership and reply availability, separate visible team IDs,
  question previews, search and per-session counts. Keep blocked/unknown questions
  visible; exclude errors, teammates and stopped residue. Opening is read-only.
  No ranking, unread/resolve state, queue API, persistence or notification service.
- Select the exact run/agent once, preserving drafts and compact detail ownership.
  Guard send completion with selection and draft epochs, including same-text ABA
  edits. Add native full-question keyboard reading, changed-count announcements,
  poll-stable reading position and visible focus fallback after removal.
- Adopt contextual disclosure, efficient invocation and cautious adaptation from
  [Microsoft's Human-AI Interaction guidelines](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf).
  Apply [mixed-initiative interaction research](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/11/chi99horvitz.pdf)
  by exposing needed dialogue without forcing interruption. These are design
  interpretations, not empirical proof of this implementation's user benefit.
- Apply [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html),
  [focus order](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html) and
  [native button semantics](https://www.w3.org/WAI/ARIA/apg/patterns/button/).
  Reject inferred priority, auto-navigation and assertive whole-queue announcements.
  No external code or assets are copied. Defer draft badges and stopped-task
  carry-forward as separate features with different state/permission tradeoffs.
- Independent review tightened membership, exposed IDs outside clamped text,
  preserved question scroll and revealed removed-card fallback. Cover real Engine
  pause/peer/deadline/reply/stop transitions, deferred UI races and 20-session
  synthetic Windows Edge interaction at desktop/tablet/narrow widths.
- The first real Edge pass exposed a long-task/long-question composition that
  clipped Send on desktop. Allow the bounded, keyboard-scrollable question region
  to shrink to a usable minimum; retain the strict composer visibility assertions.
  The next Edge pass completed the new feature cases, then exposed an older send
  test expecting stale feedback after editing a draft. Replace that expectation
  with a held exact POST/acceptance check and preserve the newer unsent draft;
  subsequent cross-agent send cases remain unchanged.
- Preserve the exact preceding documentation-revision PR overview and provenance
  in the evidence index. Final local counts, source/PR CI, artifacts and independent
  review belong to the exact-head handoff. No live inference, user-PC execution,
  dependency, permission, binary packaging or five-job CI policy changes.

## Documentation revision 1 — internal deployment review (2026-10-06)

- Add one short Japanese [IT review checklist](IT_REVIEW_CHECKLIST.md), linked from
  README and Windows setup. Its behavior baseline is `0.1.1.dev25`, source commit
  `497b549bec320020dd35696ab0871ef45ca832b9`; the application version stays unchanged.
- Gather separate installation, runtime-destination and data-handling decisions;
  link existing instructions instead of adding another installation procedure.
  Keep approvals blank, and distinguish hashes, private IPs and CI from company approval.
- Cover enabled initial profiles, offline-install versus inference behavior,
  separate proxy/CA settings, retained retired-key masks and explicit state-directory
  ACL caveats. No application, default, dependency, permission or CI behavior changes.
- Check the existing approach against [pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/),
  [local-package installation](https://pip.pypa.io/en/stable/user_guide/#installing-from-local-packages),
  [Python ensurepip](https://docs.python.org/3/library/ensurepip.html) and
  [Microsoft icacls](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls).
  These references explain mechanisms, not approval or compatibility of this deployment.
- Validate Markdown references and source consistency. Fresh exact-head five-job CI
  and independent review belong to the public handoff; prior evidence keeps its scope.

## 0.1.1.dev25 — Python-independent setup help (2026-10-06)

- Reproduce a bootstrap usability gap: the CMD entrypoint checked for an approved
  interpreter before processing `--help`. A user could not read option help before
  Python selection. Add fixed, English ASCII usage/examples for `--help`, `-h` and
  `/?` before that check. Help must be the first and only argument; extra arguments,
  including an explicitly empty quoted argument, return an error without setup.
- Explain the existing temporary `WORKBENCH_PYTHON` selection, separately approved
  standard CPython, preflight, proxy/CA and offline choices. Help does not run
  Python, validate prerequisites, create `.venv`, install packages or use network.
- Keep the normal CMD body and its complete argument forwarding unchanged. Python
  selection, source installation, version support, proxy/CA containment, offline
  behavior and the PowerShell compatibility wrapper retain their existing rules.
- Apply Microsoft's [CMD quoting guidance](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd)
  and [batch parameter semantics](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/call):
  keep help as static echo lines outside command groups, never expanding user
  environment values into its output. Use native Windows tests for actual parsing.
- Defer a new Python-path argument or interactive picker: the existing two-line
  flow already avoids persistent settings, and another selector does not solve
  organizational approval. [SHIFT leaves `%*` unchanged](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shift),
  so consuming a selector would require a new forwarding contract. Do not promise
  untested drag-and-drop behavior or add discovery through PATH/registry/launchers.
- Retain the launcher restriction because [Python install-manager launch paths](https://docs.python.org/3/using/windows.html#installing-runtimes)
  can install a missing runtime. No new dependency, installer redesign, policy
  bypass, bundled build, UI change, live inference or user-PC execution is added.
- Preserve the exact preceding dev24 public PR description and byte provenance in
  the evidence index. Fresh exact-head source/PR CI and independent review are
  recorded in the public handoff; historical checks retain their named scope.

## 0.1.1.dev24 — clarify data-use limits (2026-10-06)

- Keep the existing readiness destinations, file scope and Web explanation. Add one
  small in-place paragraph distinguishing LOCAL APP from inference location and
  explaining cross-profile sharing and unverified downstream data handling.
- Correct the README/SECURITY Local-only recommendation: private-LAN addresses do
  not establish company approval or rule out server-side forwarding. File reads
  enter model conversations; the copy does not claim that access grants permission
  under organizational policy. All PM and worker endpoints need the relevant review.
- Adopt the transparency principle from [Microsoft's responsible agent design
  guidance](https://learn.microsoft.com/en-us/agents/design-guidelines/responsible-ai):
  explain information use and system limits where users choose the task's models.
  The wording is grounded in this application's provider, teammate and Web flows,
  not in assumptions about any provider's retention or training policies.
- Reject approval badges, private-IP trust labels, automated probes and a new policy
  engine. No extra settings section, control, persistence, telemetry or data-routing
  behavior is added. Existing native forms, styles and asynchronous ownership remain.
- Add repeated Local-only/mixed-provider copy checks and real Edge desktop/narrow
  focus, wrapping and reachable-control checks, retaining the prior browser suite.
  Source-only installation and all five CI jobs remain unchanged. Final exact-head
  CI, screenshot inspection and independent review belong to the public handoff.
- Preserve the full preceding dev23 public PR description and byte provenance in
  the evidence index; historical checks are not relabeled as dev24 acceptance.

## 0.1.1.dev23 — source-only installation (2026-10-05)

- Follow the requirement that Python is separately approved and installed by the
  organization. Discontinue bundled prototypes/builds/distribution preparation,
  including evaluation-only mode, and remove the portable CI job.
- Make the former builder CLI, direct assembly API and PyInstaller spec fail before
  downloads, subprocesses or build output. Keep historical evidence and offline
  synthetic notice helpers without treating them as current distribution support.
- Preserve source Setup/Launch and approved 64-bit CPython 3.11–3.13 support. Require
  the explicit local path of an existing approved interpreter, avoiding install-capable
  launcher aliases rather than relying on environment switches that manager settings
  can override. Do not change the caller's persistent settings.
- The [legacy launcher documentation](https://docs.python.org/3.13/using/windows.html#install-on-demand)
  and [install manager configuration](https://docs.python.org/3/using/windows.html#configuration)
  describe why aliases cannot guarantee read-only discovery. Python itself is not
  installed or upgraded by this change. Hosted CI supplies its own test runtime.
- Based on verified dev21. No unpublished dev22 changes are included. Application
  security behavior, dependencies, frozen compatibility helpers and UI are unchanged.
  Test results apply only to the named source head and are recorded at handoff.

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

Actual frozen execution reached authenticated Edge startup on the next internal run.
The acceptance driver then compared a Windows 8.3 temporary-directory alias with
the server's canonical long path. Correct the test to compare native filesystem
identities, keep exact protected-root assertions, and record synthetic preflight
scope for diagnostics. No production deny boundary is weakened.

## 0.1.1.dev6 — Selected-detail polling and stable navigation (2026-10-05)

- Preserve the full `/api/state` default contract. Add an explicit selected view
  retaining all public run/agent metadata and live reply eligibility while loading
  full retained logs, reports and save receipts only for the selected agent.
- Filter selected-run activity before the existing 100-item visible limit. Construct
  summaries before history allocation/redaction; never serialize everything first.
- Keep the cockpit layout, providers, configuration, file scopes, result provenance,
  export behavior and experimental portable distribution gates unchanged.
- Treat navigation as a generation, not merely an ID pair. A delayed response cannot
  regain authority after A → B → A. Loading is distinct from an empty history, and
  unchanged polling preserves existing controls and content nodes.
- Benchmark bounded synthetic small/medium/report-retention profiles through the
  real authenticated loopback endpoint. Keep conversation eligibility work in the
  fixture and separate body bytes, snapshot time, JSON time and HTTP measurements.
  These are development-machine observations, not production Windows guarantees.

Research decisions:
- [HTTP representation validators and conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-13):
  defer ETags and 304 optimization. Eligibility can change at a time limit without
  a new event or report; a sequence-only validator would hide a meaningful change.
  Existing authenticated `no-store` responses remain unchanged.
- [Fetch cancellation](https://developer.mozilla.org/en-US/docs/Web/API/AbortController/abort):
  cancellation can reduce unnecessary fetch work, but cannot substitute for checking
  which navigation owns a response. Adopt generation validation and a single-flight
  follow-up request; defer extra cancellation/streaming machinery in this cycle.
- [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  distinguish loading from a true empty result without moving keyboard focus. Keep
  status updates separate from the agent's report and preserve stable DOM content.
- Defer automatic persistence, history eviction and explicit session forgetting.
  The 20-run admission limit still applies. A future manual forgetting feature needs
  a clear confirmation and race-safe active/question/stop-drain guards; it must never
  delete workspace files as a side effect.

No live inference, user PC, credentials, external telemetry or new runtime dependency
is required. Source changes remain in the existing draft PR; no merge or release is
part of this cycle. Exact-head Windows Edge and all CI jobs remain required evidence.

First Windows cycle-6 CI correction: the expanded deferred-frontend harness passed
its complete JavaScript source through `node -e`, exceeding Windows CreateProcess's
command-line limit. Stream the same source through `node -` stdin instead, with a
70,000-character regression. This changes test transport only; production behavior
and the behavioral assertions stay intact. Fresh exact-head CI is required.

The same Windows run passed all real Edge interaction checks, including compact
navigation and stable nodes, before benchmark-report output hit redirected cp1252
stdout. Emit ASCII-escaped JSON (decoded values unchanged), and test the CLI under
an explicit legacy encoding. This fixes evidence transport, not the measured API
serializer or application character handling. No initial failed job is called green.

## 0.1.1.dev7 — Stable configured-model attribution (2026-10-05)

- Reproduced the old roster relabeling completed work when the same current profile
  was changed or removed. Capture a small original-run descriptor and show it in
  the existing roster and selected-agent header. Both state projections preserve it.
- Mark identity as configured, with the actual response model unverified. Do not
  infer how a remote server resolved an alias or whether inference succeeded.
- Add run/agent/profile identity to the existing explicit report/receipt text export.
  Keep copying, record selection, report provenance and file-save semantics unchanged.
  Quote metadata names/model strings so embedded newlines cannot masquerade as fields.
- Normalize the already-optional profile label/model fields on settings validation.
  Review found that an accepted label-omitted configuration could otherwise fail the
  new descriptor capture and the existing preflight; missing models now reach the
  ordinary admission blocker. Required fields and accepted input scope do not change.
- Independent review found that redaction based only on current environment-key
  references could reveal an old descriptor after profile deletion. Redact the
  allowlisted descriptor at admission while its original references exist, then apply
  ordinary snapshot redaction again. Do not alter private inference configuration.

Research decisions:
- [MLflow run parameters](https://mlflow.org/docs/latest/api_reference/rest-api.html#log-param):
  adopt immutable run-scoped configuration identity rather than a mutable-profile
  join. Reject adding its service, telemetry, database or tracking dependency.
- [W3C PROV-DM](https://www.w3.org/TR/prov-dm/#section-entity-activity): retain the
  distinction between a generating activity's original context and later changed
  configuration. Reuse run/agent IDs; defer graphs and PROV serialization.
- [Microsoft HAX G11](https://www.microsoft.com/en-us/haxtoolkit/guideline/make-clear-why-the-system-did-what-it-did/):
  make explanations factual and limited, because an explanation can itself increase
  trust. Configured identity does not certify the served model or output quality.
- Reject broad configuration export, per-call traces and automatic archives. No
  endpoints, proxy settings, environment names, policy or file scopes are needed
  for this attribution descriptor. No runtime dependency or external call is added.

Deferred next-cycle candidate: `web_fetch` currently decodes all accepted text as
UTF-8 with replacement. A no-network synthetic Shift_JIS HTML response with an
explicit charset silently corrupted Japanese text. [W3C encoding guidance](https://www.w3.org/International/questions/qa-html-encoding-declarations)
and the [WHATWG Encoding Standard](https://encoding.spec.whatwg.org/) support a
separate declaration-aware decoding design, but label mappings, precedence, missing
and malformed declarations, and strict failure behavior need their own reviewed
scope. This cycle intentionally makes no web-fetch change.

Verification: focused descriptor/privacy/frontend tests and the actual Windows Edge
flow cover profile rename, model change, profile removal, new versus retained runs,
byte-identical old exports, and desktop/narrow layout. Final full-suite and exact-head
six-job CI results belong to the cycle handoff; earlier results are not evidence for
this head. Existing no-binary-distribution and no-live-inference gates remain.

First cycle-7 Edge acceptance caught a real tablet regression: the extra configured
identity line displaced the Send control in the long-question view. Narrow roster
identity also obscured assignment text. Keep roster identity to two compact lines
and make the full selected heading a bounded, keyboard-focusable scroll region.
The original strict composer geometry assertion remains, with added maximum-length
identity, keyboard-scroll persistence and narrow assignment-visibility checks.
A fresh exact-head full CI and screenshot review is required after this correction.

## 0.1.1.dev8 — Strict web text decoding with provenance (2026-10-05)

- Fix the reproduced Shift_JIS corruption with explicit supported declarations and
  CP932 compatibility labels; isolate decoding from the unchanged network transport.
- Select BOM, HTTP charset and bounded early HTML meta in precedence order. XHTML
  uses its own anchored XML declaration; JSON stays UTF-8. Report the actual codec,
  selection source and any UTF-8 assumption before long tool text.
- Fail visibly on selected unsupported/ambiguous declarations and malformed byte
  sequences, without echoing response bytes/labels or claiming the source is corrupt.
  Recommend an explicitly supported charset or UTF-8 export. Do not try another codec.
- Keep strict size/security limits and untrusted status. Compute output truncation
  after HTML extraction/control cleanup; flush trailing parser text before measuring.
- Independent review found and regressed five ambiguity paths: Unicode label folding
  (Kelvin sign), self-closing raw/inert HTML tags, double-escaped script content,
  ASCII XML prologs claiming UTF-16 and BOM-less NUL-interleaved JSON. The conservative
  meta scan now stops at the first raw/inert element instead of approximating browser
  script parsing. UTF-32 signatures are rejected before overlapping UTF-16 signatures.
- Add no-network declaration/error/boundary tests, a real local proxy/redirect fixture,
  and frozen-EXE acceptance through a fixed loopback proxy for every supported codec
  family plus malformed UTF-8. The proxy never forwards to the numeric public URL.

Research decisions:
- [WHATWG HTML encoding determination](https://html.spec.whatwg.org/multipage/parsing.html#determining-the-character-encoding):
  adopt BOM/header/meta ordering and the 1,024-byte bound. Defer locale guessing,
  full parsing/restarts and browser state-machine emulation. Stop before raw/inert
  content, documenting the intentional compatibility boundary.
- [WHATWG Encoding](https://encoding.spec.whatwg.org/#names-and-labels): adopt a closed
  label map and HTML legacy-label semantics. Reject arbitrary Python codec lookup,
  UTF-7/UTF-32 and byte transforms. Python legacy decoders are a bounded supported
  subset, not a claim of complete WHATWG decoder parity.
- [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259#section-8.1): keep application/json
  UTF-8 regardless of charset parameters; tolerate only the UTF-8 BOM.
- [RFC 7303](https://www.rfc-editor.org/rfc/rfc7303#section-3.2): keep XHTML separate
  from HTML meta processing, with BOM/header priority and XML declaration/default.
- [Python codec documentation](https://docs.python.org/3/library/codecs.html#standard-encodings):
  use fixed built-in codec names. A local Python 3.12 probe found windows-31j absent
  from runtime aliases despite newer documentation listing it; explicit aliases avoid
  version-dependent behavior. CP932 is intentionally selected for Japanese Windows
  compatibility, and actual frozen codec execution is tested rather than inferred.
- Reject charset-detector dependencies, external services, replacement decoding and
  silent retry guesses. A successful strict decode is not proof that a declaration
  matches the publisher's intended characters. Preserve the baseline interface.

Final local/exact-head Windows and six-job CI results belong to the cycle handoff.
The source PR remains draft; no merge, release or binary distribution is included.
## 0.1.1.dev9 — Bounded credential-mask lifetime (2026-10-05)

- Reproduced old-key exposure in retained tasks, assignments, names, roles,
  questions and mail metadata after replacing/removing a credential reference.
  Existing capture-redacted reports survived, but late responses, errors and
  successful save receipts could be retained raw. Completed-run continuation could
  also re-emit raw private conversation text after the original key was forgotten.
- Keep recognized values in a private, process-lifetime output-only registry,
  capped at 512 distinct values and 2 MiB UTF-8 payload. Preflight key/config changes
  atomically and reject overflow without dropping old masks or changing settings.
  Preserve exact-value matching, raw private protocol and workspace files.
- Separate masks from auth. Resolve new provider/diagnostic/search requests with
  current credentials; keep already-dispatched headers stable. Search uses a
  per-dispatch copy rather than a retained authenticating key. Remove memory auth
  when a provider ID disappears or its kind/endpoint/env source changes; likewise
  for search identity changes. Reserve `search` to remove the namespace collision.
- Independent review found that a large escaped regex alternation still stalled
  on mixed shared-prefix near-matches. Replace it with literal searches and a heap
  bounded by key count. Longest at the earliest match wins; emitted mask markers
  never become new input. Add the exact 512-key/2-MiB counterexample as a regression.
- Preserve full/selected state contracts, compact-history ownership, UI layout,
  strict web decoding, provider transport and the no-binary-distribution gates.

Research decisions:
- [OWASP Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude):
  adopt consistent masking of recognized credentials across public output sinks,
  safe failure handling and lifecycle regression tests. Do not add remote logging,
  arbitrary sensitive-data classification or new persistence.
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html):
  keep credential use distinct from retired output masks. Document the increased
  process-memory lifetime and zeroization limit instead of claiming old secrets
  have been erased. No vault, background rotation or new credentials are added.
- [Python literal string search](https://docs.python.org/3/library/stdtypes.html#str.find)
  and [heap queues](https://docs.python.org/3/library/heapq.html): reuse standard
  library primitives and bound pending matches to the registry size. Reject regex
  alternation after the measured stall and a per-character Python trie because
  payload limits would not adequately bound its object overhead.
- Defer retroactive browser/clipboard/download recall and redaction of editable
  config metadata; those cannot be represented as harmless read-only projection
  changes. Explicitly narrow the public guarantee. No source can certify transformed
  secrets or arbitrary private data have been removed by an exact-value matcher.

Synthetic full/selected HTTP benchmarks now include ordinary and near-count-cap
registries, with a separate maximum-payload adversarial CLI. Exact-head Windows Edge
and all six CI jobs remain required evidence; local tests are not browser verification.
Source stays in draft PR2. No merge, release, binary upload or live inference is added.

The first dev9 Windows matrix exposed a test-only locale assumption: new assertions
read the UTF-8 Japanese settings file using the runner's cp1252 default. Make every
new text-fixture read explicitly UTF-8; production already used that encoding. Edge
passed the memory-key scenario but stopped at the environment replay's expected
synthetic authentication marker. Keep that assertion and add bounded, already-public
diagnostics while investigating; the failed run is not final acceptance evidence.

The next Windows matrix passed, while Edge failed earlier on an incomplete worker
record. Review of the [locked Playwright 1.62.1 polling implementation](https://github.com/microsoft/playwright/blob/v1.62.1/packages/playwright-core/src/server/frames.ts#L1523-L1540)
confirmed the shared test helper's async predicate returned a truthy Promise before
the fetched state was ready. Replace that helper with bounded explicitly awaited
API polling and return the exact satisfying snapshot. Regress delayed false/empty
states and receipt readiness without a browser; retain every original assertion.
Forty concurrent-polling loopback repetitions had passed because they already awaited
their state reads correctly. Production redaction was not changed for this correction.


## 0.1.1.dev10 — Contained corporate setup and actionable failures (2026-10-05)

- Reproduced inherited `PIP_PYTHON` and `global.python` redirecting even a read-only
  pip command into the base interpreter. Pin every pip invocation before config reads,
  reject alternate roots/interpreters and trusted-host settings, and require the
  expected real virtual-environment prefix before installing packages.
- Independent review reproduced quiet/scope flags hiding active forbidden settings
  and inherited pip logging writing captured configuration values elsewhere. Override
  inspection-only output/scope controls and its log destination, require a positive
  environment marker, and retain the original approved install transport settings.
- Report fixed failure stages/recovery guidance without echoing captured config,
  command arguments or raw runner exception strings. Preserve existing environments,
  hash-locked binary dependencies, offline isolation and no-network local app install.
- Add environment/config rejection, old-pip failure, private-prefix, stage privacy,
  real pinned-pip, hidden-config and log-suppression regressions. Preserve basic GUI,
  credential-mask lifetime/auth separation and all prior acceptance assertions.

Research decisions:
- [pip interpreter selection](https://pip.pypa.io/en/stable/topics/python-option/)
  and [configuration precedence](https://pip.pypa.io/en/stable/topics/configuration/):
  use explicit `--python` (introduced in pip 22.3), with safe failure for older pip.
  Inspect effective configuration through the supported CLI, not pip's internal API.
- [pip TLS certificates](https://pip.pypa.io/en/stable/topics/https-certificates/):
  preserve approved PEM and system-store behavior; reject trusted-host bypasses.
  System-store defaults depend on pip version, so do not silently upgrade pip or
  promise that Windows CA registration alone always resolves installation errors.
- [Python venv](https://docs.python.org/3.13/library/venv.html#how-venvs-work):
  validate private environment identity and retain the documented recreate-after-move
  recovery path. Do not delete environments or silently repair global Python.
- [Microsoft App Control events](https://learn.microsoft.com/en-us/windows/security/application-security/application-control/app-control-for-business/operations/event-id-explanations):
  provide the failure time/file to IT for existing-event diagnosis. Reject security
  bypasses, elevation, firewall changes and automated policy/log reconfiguration.
- Defer Python auto-download, a new installer UI and binary distribution. Existing
  approval, native-license and company-policy limits remain unchanged.

Exact-head Windows matrix, real Edge and evaluation-only package evidence are required
for the handoff. No live inference, binary uploads, release, merge or deployment.


The first dev10 Windows run passed Edge and the other matrix tests, but the new
Japanese-path setup regression failed while capturing `pip --version`. A deterministic
local reproduction using `PYTHONIOENCODING=cp1252` confirmed Windows-style redirected
output could not encode the extraction path. [Python's stream documentation](https://docs.python.org/3/library/sys.html#sys.stdout)
confirms Windows pipes use the ANSI code page. Give captured Python subprocesses a
private UTF-8 output/decoding contract, retain ordinary console behavior and caller
environment, and keep the original strict config-rejection assertion. This is a real
source-installer path fix; the failing run is not final acceptance evidence.

## 0.1.1.dev11 — Start/Stop response ownership and accepted-run recovery (2026-10-05)

- Reproduced a successful creation followed by failed state refresh leaving the
  original form enabled, and delayed creation overriding a newer navigation choice.
  Keep the accepted run ID until ordinary polling observes it, with no automatic
  creation replay. Disable Start while that accepted result remains unobserved.
- Distinguish accepted creation from an unknown response. A transport/server failure
  or malformed successful response does not prove no team was created. Explain the
  uncertainty before any user-directed retry; no server idempotency or persistence
  is claimed. Independent review caught successful JSON `null` bypassing that copy;
  validate response object shape and regress null/arrays/primitives/invalid JSON.
- Give user navigation, task-dialog lifecycle, draft edits, and settings navigation
  their own generations. A late result cannot regain authority after A → B → A or
  close a newly opened dialog. Automatic initial state selection is not a user
  navigation, so state observed before the POST response still reconciles correctly.
- Reproduced a late Stop failure enabling Stop on another completed team. Use one
  current-state predicate in both rendering and the action, with per-run pending
  guards across polling and independent concurrent Stops. Re-render after responses;
  never enable whichever shared button happens to be visible. Feedback names the
  affected run and cannot replace a newer operation's notice.
- Preserve the cockpit, drafts, focus, retained results/export, compact-state
  ownership, server-side stop/write draining, credential handling and settings lock.

Research decisions:
- [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  use concise, programmatically exposed acceptance/waiting/error feedback without
  forcing focus to follow a late response. Preserve the existing live regions and
  avoid new modal alerts or verbose per-poll announcements.
- [HTTP idempotency and retries](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2):
  distinguish observing an accepted operation from repeating a non-idempotent POST.
  Do not replay an uncertain creation or claim cross-reload exactly-once behavior;
  a server-side idempotency contract is deferred to a separate design.
- [Microsoft HAX correction guidance](https://www.microsoft.com/en-us/haxtoolkit/guideline/support-efficient-correction/):
  adopt recoverable explicit state and retained drafts. Reject automatic retries
  that can duplicate a team's work. These principles do not establish full WCAG
  conformance or a model-quality guarantee.
- Defer a separate confirmed credential-recovery improvement: the server can accept
  a replacement memory-only key during a recoverable run error, but the UI settings
  lock requires stopping first. Unlocking only the correct saved credential identity
  needs its own review; no credential UI or authentication behavior changes here.

Tests use deferred synthetic transport through actual frontend callbacks and real
Windows Edge interactions. They retain all prior source/Engine/browser assertions.
Exact-head six-job CI and screenshot acceptance belong to the final handoff. No
live inference, user-PC operation, binary upload, release, merge or deployment.

## 0.1.1.dev12 — Saved-destination memory-key recovery (2026-10-05)

- Reproduced a recoverable authentication error leaving a run waiting while the
  UI disabled every key field. The server already supported atomic replacement
  followed by an explicit same-run human message without resetting any budget.
- Separate saved provider/Brave credentials from the active-run configuration lock.
  Disclose profile/search scope, saved endpoint/proxy and subsequent-request impact.
  Keep endpoint, model, rights, budgets and diagnostics locked during active work.
  SearXNG/page fetching do not use the search key; no speculative authentication
  error classifier, automatic probe, retry or new scheduler path is introduced.
- Require a server-owned saved-config revision on every key write, including clear.
  Reject missing/stale/malformed values before mutation, without a legacy bypass.
  Keep revision outside persisted config and run eligibility; config/key failures
  remain atomic with the bounded output-mask registry.
- Guard both provider and search keys against dirty/new settings. Add a GET-only
  discard/reload action. Independent review reproduced empty worker selections
  being silently defaulted during discard; preserve the entire task draft, including
  unavailable old choices and an above-new-limit worker count for explicit correction.
- Own pending writes per target across polls and close/reopen. Preserve unrelated
  pending requests and drafts; clear submitted/abandoned password inputs. Validate
  value-free acceptance receipts and report unknown outcomes without replay.
  Separate credential feedback from diagnostic feedback and avoid transiently
  disabling focused password inputs during ordinary polling.

Research decisions:
- [Microsoft HAX correction](https://www.microsoft.com/en-us/haxtoolkit/guideline/support-efficient-correction/)
  and [consequence guidance](https://www.microsoft.com/en-us/research/blog/guidelines-for-human-ai-interaction-design/):
  adopt a discoverable, bounded correction path with explicit next-request effects.
  Reject silent reruns and claims that storing a key validates authentication.
- [W3C status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  keep concise status regions without moving focus or repeating text on each poll.
  No claim of full assistive-technology or WCAG conformance is made.
- [RFC 9110 conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1):
  apply a server-checked stale-write precondition. The JSON configuration revision
  is an application contract, not an implementation claim for HTTP If-Match.
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
  and [Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html#data-to-exclude):
  retain value-free statuses, authentication/mask separation and bounded retired
  masks. Defer vaults, persistence, automatic account-key rotation and new logging.

Tests use synthetic credentials and local fixtures only. They cover actual callbacks,
concurrent target writes, stale destination/revision races, keyboard and narrow Edge
flows, explicit same-run recovery and unchanged quota/stop/redaction protections.
Exact-head six-job CI, visual review and evaluation-only package evidence belong to
the final handoff. No live inference, real-key entry by the assistant, user-PC work,
binary distribution, merge, release or deployment is included.

The first dev12 push passed both Windows suites and real Edge; the PR Windows 3.11
job exposed an older timing assumption in the provider timeout test. Its 20-ms total
timeout expired before the loopback server observed any request. Preserve the exact
one-request/output-cap assertions, wait for real server receipt and hold the response
until the client's actual timeout instead of racing 20/100-ms sleeps. The bounded
five-second total timeout follows [aiohttp's total-timeout semantics](https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout.total).
No provider production behavior changes. Fresh exact-head full CI remains required;
a passing sibling job does not turn the failed first run into acceptance evidence.

## 0.1.1.dev13 — Truthful first-task guidance (2026-10-05)

- Reproduced the task placeholder suggesting an edit-and-test workflow even though
  the app has no command, build or test runner. Local preflight correctly admitted
  its text, but the UI never explained this fixed execution boundary.
- Replace that example with a text-only memo task, which needs a configured model
  but no file or Web permissions. Keep essential capability/limit text beside the
  textarea with an accessible description, visible after the user starts typing.
- Offer three static examples in one native disclosure: text, permitted files and
  configured public-Web research. Explain existing absolute folders, independent
  read/write permissions, supported formats and non-browser page fetching.
- Preserve task drafts, selections, native disclosure state and Start ownership.
  Examples never fill a field, change settings, grant access or make a request.
  No prompt classifier, engine/API change, provider probe or runtime dependency.
- Align the README's first-use instructions with the current settings, task and
  model-list control labels. Retention guidance remains a separate deferred change.

Research decisions:
- [Microsoft HAX input examples](https://www.microsoft.com/en-us/haxtoolkit/pattern/g1-d-demonstrate-possible-system-inputs/):
  adopt examples grounded in available operations, avoiding its identified pitfall
  of implying unsupported capabilities. Reject clickable recipes that overwrite
  drafts or run tasks. No model-quality guarantee follows from showing an example.
- [Microsoft HAX introductory explanations](https://www.microsoft.com/en-us/haxtoolkit/pattern/g1-a-introductory-blurb/):
  use concise contextual help rather than a repeated onboarding tour or wizard.
- [GOV.UK native disclosure guidance](https://design-system.service.gov.uk/components/details/):
  collapse optional example depth, but keep essential execution limits visible.
  Use the existing cockpit's appearance, not a new imported design system.
- The HAX library's historical [Google Maps input example](https://www.microsoft.com/en-us/haxtoolkit/example/google-maps-demonstrate-possible-system-inputs/)
  illustrates expectation-setting outside agent apps. Adopt the principle, not its
  imagery or a claim about the current Maps interface.

Static tests check semantics and admission without external calls. Real Windows Edge
acceptance checks keyboard/native disclosure, draft/selection/expanded-state
preservation, no hidden actions and desktop/tablet/narrow geometry. Final exact-head
six-job CI and screenshot review belong to the handoff; local browser launch remains
blocked. No live inference, user-PC work, binary distribution, release or merge.


## 0.1.1.dev14 — Contextual history lifetime and safe restart guidance (2026-10-05)

- Reproduced the 21st-run blocker recommending restart without explaining the loss
  of reports, save receipts, conversations and memory-entered keys. Keep the same
  20-run admission boundary and error code, but describe the consequence and existing
  selected-record export first. Closed-server guidance no longer implies a full history.
- Show startup run count against 20 and a compact lifetime reminder beside SESSIONS.
  Keep detailed retention/exit distinctions in a native disclosure inside the existing
  bounded results panel, rather than consuming more crew-list space or showing a modal.
- Explain server lifetime separately from browser-tab close/reload and team Stop.
  Stop retains history and does not free a run slot. A new server restores settings,
  not conversations or memory-entered keys; environment keys use the next process's
  environment. Do not promise draft restoration or authentication after browser exit.
- Keep explicit one-record UTF-8 export, receipt/file separation, current-file-unverified
  notices, redaction, omission counters and all retention enforcement unchanged. Normal
  shutdown does not delete saved workspace files, but a historical receipt cannot
  certify their current existence or content. Download-start feedback is not completion.
- Independent review caught omitted-history wording implying in-memory deletion. Narrow
  it to the display histories: private model conversation retention is separate, and
  truncating a report does not prove the underlying full reply has been erased.

Research decisions:
- [Microsoft HAX feedforward](https://www.microsoft.com/en-us/haxtoolkit/pattern/g16-a-feedforward-convey-the-consequences-of-user-actions-before-the-user-takes-action/):
  adopt concrete pre-action consequences and proportionate noninterrupting indicators.
  Reject vague restart advice and automatic exports presented as safety guarantees.
- [W3C contextual help](https://www.w3.org/WAI/WCAG22/Understanding/help.html)
  and [status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  keep help beside the operation without moving focus; preserve existing concise status
  feedback rather than announcing lifetime text on every poll. This is not a complete
  accessibility audit or a WCAG-conformance claim.
- [GOV.UK native details guidance](https://design-system.service.gov.uk/components/details/):
  keep essential lifetime information visible and optional distinctions in a disclosure.
  Preserve the established cockpit styling and keyboard/scroll behavior.
- Defer durable sessions, automatic backups, bulk export, workspace-file downloads,
  beforeunload prompts and authentication recovery. A missing browser cookie prevents
  authenticated access even while server history remains; no reauthentication promise
  follows from tab-reopen tests in a retained browser context.

Synthetic loopback tests distinguish reload/reconnect, team Stop, server cleanup and a
fresh server at the same settings directory. Real Windows Edge checks same-context
reload/tab reopen, explicit exports, keyboard and desktop/tablet/narrow geometry. Final
exact-head six-job CI and independent screenshots belong to the final handoff. Local
browser launch remains blocked. No live inference, user-PC work, binary distribution,
release, merge or deployment is included.

## 0.1.1.dev15 — Tool-result integrity after ordinary failures (2026-10-05)

- Reproduced a normal merged A1:B1 workbook edit targeting B1 that raised an
  uncaught AttributeError. Earlier writes and receipts survived, but the failed
  call and remaining calls had no results. An admitted human continuation replayed
  unmatched calls through all three provider adapters.
- Reject non-anchor merged-cell destinations with an instructive validation error
  before saving the XLSX request. Preserve the existing merge and workbook bytes;
  an explicitly requested top-left edit remains supported. No automatic unmerge,
  destination substitution or whole-file retry is introduced.
- Unexpected ordinary tool exceptions now close the attempted call and unexecuted
  remainder before entering the existing agent-error state. Preserve successful
  earlier results/receipts, native provider history and existing human admission.
  Keep the ambiguous attempted outcome explicit: a file may already be committed,
  even if its receipt was not recorded. No rollback or no-effects guarantee.
- Independent review expanded the same boundary through result-shape inspection,
  strict JSON serialization and tool-log preparation. These failures also append
  exactly one result per call; a failed logger is not retried. Nonfinite output is
  rejected rather than sent as nonstandard JSON. Fixed errors omit private exception
  details. Cancellation/draining and redaction-capacity fail-closed paths stay separate.

Research decisions:
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling):
  adopt explicit call-ID-linked result strings that can describe failure; preserve
  native output/reasoning replay. Reject dropping history to hide unmatched calls.
- [Claude tool-result handling](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls):
  preserve immediate tool-result placement and results before human text. Keep the
  current adapters; defer an SDK/tool-runner migration and optional wire refinements.
- [openpyxl merged-cell implementation](https://openpyxl.readthedocs.io/en/stable/_modules/openpyxl/cell/cell.html):
  treat non-anchor MergedCell instances as invalid write destinations. Do not infer
  user intent to alter merges or target a different cell.
- Reject automatic batch retry, fabricated success/rollback results, broader file
  permissions and UI redesign. This is bounded failure recovery, not a transaction
  manager or a promise that external tools have no side effects.

Real temporary Office files and synthetic loopback providers test every adapter,
partial committed mutations, exact result ordering, explicit continuation and
all-or-none admission of malformed provider batches. Existing stop/drain, budget,
pause/finish, redaction and receipt tests remain. Final exact-head six-job CI,
Windows Edge evidence and evaluation-only package checks belong to the handoff;
no live inference, user-PC action, binary distribution, merge or release is included.

The first dev15 source Edge run exposed an older test synchronization race in the
credential late-rejection flow. It captured a reopened-dialog baseline before the
native queued `close` event cleared the previous pending notice. The sibling PR
Edge run passed, but that does not validate the failed source run. The acceptance
helper now registers before native Escape and waits for the actual close event;
both delayed-success and delayed-409 cases assert the cleared/unknown state before
releasing the real upstream response. Exact post-response equality assertions remain.
A deterministic helper test proves that removing the `open` flag alone is not
completion. Application frontend code is unchanged; fresh full CI is required.

## 0.1.1.dev16 — Provider completion evidence and Local refusals (2026-10-05)

- Reproduced absent/null Local and Anthropic completion reasons being accepted as
  final reports or executable write/finish batches. Non-streaming replies now need
  recognized terminal reasons. Proxies omitting those fields must return protocol
  evidence rather than relying on an HTTP 200 response being treated as completion.
- Reproduced OpenAI output marked incomplete/in-progress, or carrying error/incomplete
  details with optional response status omitted, executing tools. Reject explicit
  negative evidence before returning the normalized response. Preserve documented
  optional response/item status compatibility instead of requiring every field.
- Reproduced a valid Local Chat refusal with null content disappearing from both
  display and native replay. Preserve its text alongside ordinary content, retaining
  display redaction and exact native replay. Reject non-string/non-null refusal
  values and nonempty refusal paired with actual or declared tool calls.
- Keep existing error/waiting states, human continuation, earlier receipts/reports,
  native reasoning and consumed budgets. No rejected response enters conversation
  history. Retain dev15 tool-result closure unchanged.

Research decisions:
- [OpenAI Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
  and the [official response type](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response.py):
  optional status fields are not themselves evidence of failure; explicit negative
  status, error and incomplete details must take precedence over parseable output.
- [OpenAI Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  adopt documented non-streaming finish reasons and the optional refusal string.
  Preserve refusal in native assistant replay, not only in the display projection.
- [Anthropic stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons):
  non-streaming completion needs its stop reason. Empty `end_turn` responses can be
  legitimate, so reject a broad empty-response ban. Keep paused, truncated, context-
  limited and refusal stop reasons on the existing blocked path.
- Reject automatic retries, continuation, fallback, status-schema expansion and SDK
  migration. Defer generic tool-reason/content consistency tightening; Local servers
  returning `stop` with valid structured calls remain compatible. No live model calls.

Deterministic loopback tests cover whole-response admission with text and mutation
batches, preserved prior writes/receipts, budgets and explicit continuation; direct
adapter tests preserve optional metadata and empty terminals. Full local validation,
independent review, exact-head six-job CI, real Windows Edge and evaluation-only
package evidence are required for the handoff. Frontend files remain unchanged.


## 0.1.1.dev17 — Recheck deadlines after filesystem queue waits (2026-10-05)

- Reproduced a writer queued behind another worker's read at 0.024 seconds starting
  and committing at 10.114 seconds despite a configured 10-second run limit. The
  outer tool check happened before lock acquisition; dispatch did not recheck time.
- Recheck the existing deadline immediately inside the shared filesystem lock,
  before any path resolution or executor dispatch. An expired queued operation uses
  the existing safe limit error and ordinary tool-result path. Preserve attempted-call
  accounting, spent turns, exact result closure, earlier reports and save receipts.
- Preserve started-file-operation draining and cancellation unchanged. Do not wrap
  filesystem saves in a new cancellation timer, refund queued attempts, redefine
  model calls as HTTP attempts, or add a scheduler/status/retry/configuration path.

Research decisions:
- [Python asyncio locks](https://docs.python.org/3/library/asyncio-sync.html#asyncio.Lock):
  lock acquisition waits independently of the application's run deadline. Adopt a
  fresh admission check after the asynchronous wait, before filesystem access.
- [Python cancellation shielding](https://docs.python.org/3/library/asyncio-task.html#shielding-from-cancellation):
  preserve the existing shielded operation and explicit drain. Reject forced I/O
  cancellation as a substitute for preventing an operation from starting.
- [HTTP idempotency and retry guidance](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2):
  keep conservative existing transport retry behavior. The audit confirmed bounded
  Local 503 retries use one logical model call; cancellation during backoff prevents
  later attempts and releases the resource slot. No demonstrated bug justifies
  changing that accounting contract or expanding retries.

Deterministic tests isolate the engine clock and synchronize on actual contested
lock acquisition. All three loopback provider protocols cover pre/exact/post-deadline
admission, single and multi-call results, retained output, human rejection, queued
Stop and started-save draining. Direct guards cover every filesystem tool before
path access. Full local validation, independent review, exact-head six-job CI,
Windows Edge and evaluation-only package evidence are required for the handoff.
No live inference, user-PC action, browser retry, binary distribution, merge or release.


## 0.1.1.dev18 — Hash-bound native notice and provenance evidence (2026-10-05)

- Correct the interpretation of cycle 5's keyword flags. The exact reviewed CPython
  3.13.15 LICENSE contains unlabeled OpenSSL Apache 2.0 text and Microsoft Distributable
  Code conditions, plus libffi/bzip2 text with mixed original line endings. Record
  checked original-byte spans without changing or normalizing the copied notice.
- Pin a small offline reference index to its own SHA-256. Bind comparison to exact
  Python implementation/version/platform/architecture, OpenSSL/zlib observations,
  notice size/hash and individual native paths/sizes/hashes from the previously
  verified official embed archive. Unknown or changed identities remain unresolved.
- Keep keyword observations, notice evidence and native-file provenance separate
  from component and distribution-review statuses. Case-insensitive Windows paths
  preserve VCRUNTIME matches; ambiguous case duplicates do not match. UCRT/API-set
  files absent from this archive reference remain explicitly unindexed.
- Keep zlib 1.3.1 and XZ 5.2.5 source references precise. Their missing text in the
  copied notice is an observation, not an automatic legal violation. Do not conflate
  CPython zlib with lxml's separate native copy. Reconfirm the existing LGPL text's
  exact hash against GNU without treating notice possession as source/relink compliance.

Research decisions and remaining requirements are in
[NATIVE_REDISTRIBUTION](NATIVE_REDISTRIBUTION.md). Preserve historical PR snapshots;
link this correction rather than rewriting their original observations. Defer native
rebuilds, library substitution and release decisions. No dependency changes, feature
removal, new downloads during builds, legal acceptance or binary uploads are added.

The evaluated build remains explicitly evaluation-only and distribution-blocked even
when every available reference comparison matches. Full local tests, independent
review and fresh exact-head six-job CI / Windows evidence are required for the handoff.


## 0.1.1.dev19 — Keep keyboard focus on changing logs (2026-10-05)

- Reproduced focus dropping to BODY when a new log replaces the currently focused
  native thinking-detail summary. Unchanged polling and expanded-state retention
  already worked; existing browser tests did not cover focus during changing logs.
- Give summaries a stable run/agent/log focus key. Reuse conditional body-only
  restoration with preventScroll, including direct conversation-render callbacks.
  Missing and ambiguous IDs do not become guessed index-based focus identities.
- If a focused record actually leaves the same owner's loaded retained history,
  prefer the following surviving disclosure, then a preceding survivor, then a new
  disclosure or the existing conversation heading. Loading/selection changes,
  obsolete A→B→A responses and other focused controls never trigger this fallback.
- Independent review identified near-bottom auto-follow as a second way to lose the
  visible reading target. Preserve pane scroll while a disclosure owns focus; leave
  ordinary bottom-follow unchanged when users are elsewhere. Reveal a genuinely
  evicted record's fallback only as needed; a screenshot helper must not hide a
  clipped fallback by scrolling it into view before its visibility assertion. Keep drafts and open
  details, native keyboard behavior, the cockpit design and existing async ownership.

Research decisions:
- [W3C APG keyboard interface](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/#discernibleandpredictablekeyboardfocus):
  adopt logical focus persistence after DOM replacement instead of allowing BODY to
  silently become the active element. Reject unconditional refocusing after updates.
- [WCAG focus-order guidance](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html):
  keep the current reading context and an explicit nearby fallback when its actual
  record is gone. Do not add positive tabindex values or a custom navigation mode.
- [W3C disclosure pattern](https://www.w3.org/WAI/ARIA/apg/patterns/disclosure/):
  preserve native details/summary and verify Space/Enter after new content arrives.
  Defer broad screen-reader/text-zoom certification, tablist conversion and redesign.

Tests use actual production polling/render callbacks with synthetic focus-removal
semantics, plus Windows Edge keyboard checks and desktop/narrow screenshots for
independent visual review. Full local checks and exact-head source/PR six-job CI are
required. Previous dev18 acceptance is retained in a versioned evidence record; the
frozen original PR archive and dev15 source ZIP remain untouched. No live inference,
new dependency, local browser retry, user-PC action, binary distribution, merge or release.


## 0.1.1.dev20 — Keep settings saves with their owning revision and drafts (2026-10-05)

- Reproduced two tabs reading one revision, one lowering the model-call limit,
  then the other's unrelated-label save silently restoring the older limit.
  Require the existing process-local revision on every configuration PUT. Check
  after body arrival immediately before the synchronous mutation; reject stale,
  missing and malformed ownership without a legacy bypass or partial mutation.
- Reproduced delayed Save selecting explicitly unchecked workers, clamping a newer
  task's worker count and clearing newer feedback. Preserve complete task drafts,
  including removed choices as unavailable, and restore logical worker-control
  focus only when DOM replacement left the document body focused.
- Separate accepted saved-baseline reconciliation from dialog feedback authority.
  Native close/reopen does not make an unchanged submitted form falsely dirty or
  let late success/failure paint a newer context. Dedicated draft generations and
  a captured-form comparison keep newer/ABA/unsignaled changes dirty. Independent
  review extended this through an initially pristine form with an unsignaled edit.
- Validate full value-free acceptance snapshots and the exact next revision. A
  conflict or uncertain outcome preserves the draft but blocks Save, credentials
  and model diagnostics until explicit saved-settings reload. Keep fields editable,
  explain that users should note their changes before discarding, and never replay
  a request or pretend a lost response proves no save occurred.
- Keep active-run locks, memory-only keys, atomic disk/mask behavior, budgets,
  configured destinations, native dialogs and existing cockpit styling. Migrate
  all synthetic API clients to the revision envelope without weakening tests.

Research decisions:
- [RFC 9110 conditional requests](https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1):
  adopt a server-checked precondition for the demonstrated lost-update race. Reuse
  the application's JSON revision contract; do not claim HTTP If-Match compliance
  or add a general transaction/idempotency service.
- [W3C status messages](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html):
  preserve concise accessible outcome feedback without moving focus or replacing
  newer feedback. This does not establish full accessibility conformance.
- [Microsoft HAX correction guidance](https://www.microsoft.com/en-us/haxtoolkit/guideline/support-efficient-correction/):
  preserve editable drafts and an explicit recovery path. Reject silent merge,
  automatic resend, guessed defaults and destructive automatic reload.
- Defer cross-tab live synchronization, retained edit history, persistent revision
  tokens, automatic backups and generic undo. Configuration conflicts justify this
  bounded precondition; no new provider, credential storage or runtime dependency.

Real loopback API tests cover two-client/concurrent/streamed-body/ABA races and
atomic failures; production callbacks cover old responses, exact draft retention,
malformed receipts and locks. Real Windows Edge acceptance covers two tabs, actual
queued native close, delayed committed responses, unknown transport and keyboard /
desktop/narrow state. Full local checks, independent source/evidence/pixel review
and exact-head six-job CI belong to the final handoff. Preserve the previous compact
PR overview as a hash-bound historical record, along with all earlier evidence and
the frozen original PR archive. No local browser retry, live inference, user-PC work,
binary distribution, merge or release is included.


## 0.1.1.dev21 — Preserve successful terminal batches at limits (2026-10-05)

- A bounded transition audit first found no discrepancy across 32 seeded schedules
  of 96 action-selection slots. A targeted terminal-state oracle then reproduced
  `finish_work` followed by a skipped sibling at the one-tool limit: the report was
  recorded successfully, but the skipped sibling changed the agent to an error.
  Independent review reproduced the same issue for `ask_user` and for a deadline
  crossed immediately after the successful terminal tool.
- Let the existing closed-batch flag precede budget admission for remaining skipped
  calls. Preserve one result per call, successful completion/question state, spent
  counters, rejection of expired continuation and existing text-only continuation.
  Invalid terminal arguments do not close the batch or bypass budget enforcement.
- Keep four controlled legal-session schedules and a small fixed-seed model as
  regression coverage. Use explicit events and task completion rather than sleeps,
  independent expected acceptance/counters/configuration rather than copying the
  engine's eligibility implementation, and readable normalized traces on failure.

Research decisions:
- [Hypothesis stateful-testing guidance](https://hypothesis.readthedocs.io/en/latest/stateful.html):
  adopt composable actions, returned identities, preconditions and invariants checked
  after each action. Keep a small standard-library scheduler instead of adding a new
  dependency or replacing the existing targeted tests.
- [TLA+ safety-property guidance](https://docs.tlapl.us/creating:safety): preserve
  reachable action traces for counterexamples. Distinguish bounded safety checks
  from exhaustive verification and liveness proofs; neither is claimed here.
- Defer a general model checker, automatic trace minimizer, broad fuzzing framework
  and runtime scheduler rewrite. The demonstrated false terminal error justifies a
  narrow guard-order repair, not new budget semantics or a product feature.

The 30 boundary cases use all three real loopback provider adapters; nine session
cases cover queue saturation/human priority, Stop/completion ordering, captured
gate-waiter credentials versus undispatched mailbox work, config-save ownership,
and four bounded model traces. Full local checks, independent review and exact-head
source/PR six-job CI belong to acceptance. UI design, permissions, runtime dependencies,
historical evidence and the dev15 source ZIP remain unchanged. No local browser retry,
live inference, user-PC action, binary upload, merge or release is included.
