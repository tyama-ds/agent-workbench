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
