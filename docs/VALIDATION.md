# Validation scope

Commit-specific runs, artifact links and historical review records are indexed in
[evidence/README.md](evidence/README.md). The archived PR snapshot is historical;
use the live PR’s explicitly named head for current acceptance. Counts below describe
the named development revisions, not automatic acceptance of later documentation edits.

## Current revision — native evidence comparison (2026-10-05)

Version **0.1.1.dev18** adds an offline comparison of the evaluation build's original
CPython notice bytes and actual native-file inventory against a checksum-pinned,
reviewed CPython 3.13.15 Windows x64 reference. Keyword observations, notice-content
matches, per-file archive matches and unresolved distribution review are separate.
The reference was checked against the official archive during review; builds do not
download it, execute its binaries, or infer whole-bundle provenance from one match.

Synthetic tests cover unlabeled notices, original-byte and manifest-hash changes,
name-only false positives, version/platform/architecture and observed-version drift,
invalid spans, native path/hash/size mismatches, case ambiguity, unindexed UCRT/API-set
files, reference-index tampering and unchanged distribution/upload gates. A source
notice's absence is not automatically a finding of noncompliance. See the
[current correction and remaining requirements](NATIVE_REDISTRIBUTION.md).

Local aggregate: **1055 passed, 6 platform-specific skips**, including **28 new
evidence cases**. Dependency consistency, Python compilation, JavaScript syntax and
whitespace checks pass. Independent review, exact-head six-job CI and fresh Windows
Edge / evaluation-only package evidence belong to the cycle handoff. Runtime dependencies,
locks, application behavior and source-install flow are unchanged. No binary release,
source-offer commitment, license acceptance or legal clearance is included.

## Prior revision — queued filesystem deadlines (2026-10-05)

Version **0.1.1.dev17** rejects file operations that expire while waiting for the
shared filesystem lock, before path resolution or executor dispatch. The existing
attempted-call accounting, result history, earlier reports/receipts and started-save
draining remain unchanged. Provider retry policy and logical model-call counts are
not redefined.

Deterministic tests use an engine-only controlled clock and an observed real lock,
without short timer races. All three loopback HTTP provider protocols cover the
pre-deadline success path, inclusive/exceeded deadline rejection, single/multi-call
result closure, retained earlier output, continued spent budgets, rejected human
continuation, cancellation while queued and draining of started saves after expiry
or Stop. Every filesystem schema is checked for rejection before path access.

Local aggregate: **1027 passed, 6 platform-specific skips**, including **44 new
deadline cases**. Exact-head six-job CI, actual Windows Edge, independent review
and evaluation-only package evidence belong to the final handoff. No frontend,
permission, retry, public-state, persistence or binary-distribution change is added.

## Prior revision — provider completion evidence (2026-10-05)

Version **0.1.1.dev16** checks non-streaming completion evidence before accepting
reports or executing any call. Local/Anthropic missing, null, unknown and incomplete
terminal reasons are rejected. OpenAI optional statuses remain compatible while
explicit negative item status, error and incomplete details reject the entire reply.
Local refusal text is visible, redacted for display and preserved exactly in replay;
malformed refusal values and refusal/tool contradictions are rejected.

Synthetic loopback HTTP tests exercise text and mixed write/finish batches,
unchanged earlier committed output and receipts, consumed budgets, explicit human
continuation and safe public error states. Optional OpenAI metadata and legitimate
empty terminal replies remain covered. Truncated second-call arguments cannot
execute an earlier valid write. Existing dev15 result closure, cancellation,
credential redaction, retention and GUI tests remain in the full suite.

These fixtures validate application behavior and wire structure, not live-provider
acceptance. Local aggregate: **983 passed, 6 platform-specific skips**, including
**98 new completion/refusal cases**; the focused provider/integrity suite has
**174 passed**. Exact-head six-job CI results, actual Windows Edge and evaluation-only
package evidence belong to the final handoff. No browser launch retry, new public
status, automatic provider retry or binary distribution is added.

## Prior revision — tool-result integrity after failures (2026-10-05)

Version **0.1.1.dev15** rejects non-anchor merged-cell writes without saving that
XLSX request and closes provider batches after unexpected ordinary execution or
result-preparation failures. Real loopback HTTP fixtures exercise Local Chat,
OpenAI Responses and Anthropic Messages with exact call/result pairing and ordering,
explicit human continuation, and preserved actual writes/receipts. Tests distinguish
failure before execution, after commit but before receipt, after receipt, invalid
result shapes, cyclic/nonserializable/nonfinite output and tool-log exceptions.
Mixed malformed/duplicate/unknown call batches execute no earlier valid operation.
Cancellation/draining and redaction-capacity special paths remain covered.

These fixtures validate application behavior and wire structure, not live-provider
acceptance. No UI, provider destination, permission or automatic retry is added.
Local aggregate: **885 passed, 6 platform-specific skips**, including **42 new
integrity cases** and a native-close synchronization helper regression. Exact-head six-job CI, Windows Edge and evaluation-only packaged
acceptance evidence are recorded in the draft PR handoff.

## Prior revision — contextual history lifetime (2026-10-05)

Version **0.1.1.dev14** explains the lifetime of retained history, the 20-run boundary
and explicit selected-record exports. Same-cookie page reload/tab reopen and team Stop
retain server history; a new server keeps settings and saved workspace files but starts
without runs or memory-entered keys. Enforcement, export scope and authentication are
unchanged. Final local and independent suites: **842 passed, 6 platform-specific skips**.
Exact-head six-job CI, Windows Edge, packaged acceptance and independent screenshot
evidence are recorded in the draft PR handoff.

## Prior revision — truthful first-task guidance (2026-10-05)

Version **0.1.1.dev13** explains fixed execution limits beside the task input and
provides optional static examples for text, permitted files and configured public
Web research. No application JavaScript, engine, permissions or network behavior is
changed. Local aggregate: **834 passed, 6 platform-specific skips**. Exact-head
Windows Edge, four Python/OS jobs, evaluation-only packaging and independent pixel
review remain required for final acceptance; consult the draft PR handoff for the
final head and results. The focused validation scope appears below.

## Prior revision — saved-destination credential recovery (2026-10-05)

Version **0.1.1.dev12** permits memory-key correction for saved provider/Brave targets
without unlocking active-run configuration. A mandatory server configuration revision
rejects stale destination writes; real callbacks own pending operations and preserve
unrelated drafts. Local aggregate: **830 passed, 6 platform-specific skips**. Exact-head
Windows Edge, four Python/OS jobs and packaged evaluation are still required for final
acceptance; consult the draft PR handoff for those results and reviewed screenshots.

## Prior revision — Start/Stop response ownership (2026-10-05)

Version **0.1.1.dev11** retains accepted Start identity until observed, prevents replay
on observation failure, and preserves newer dialog/navigation/draft ownership. Stop
uses per-run pending guards. Its source and real Edge assertions remain in the suite.

## Prior revision — contained corporate setup (2026-10-05)

Version **0.1.1.dev10** pins every pip invocation to the expected private interpreter,
rejects inherited install redirection and trusted-host settings, and reports safe
stage-specific setup failures. Read-only real-pip probes verify that config inspection
cannot execute an alternate interpreter, hide active settings through quiet/scope
options, or write captured configuration to an inherited log. Positive output evidence
is required. Stubbed failure tests prove dependencies are not installed after rejection.
Older pip without `--python` fails closed; no automatic upgrade or user config edit is
performed. Existing Windows repeated-offline/CMD tests and Edge/portable acceptance
remain required. Exact-head CI evidence belongs to the draft PR handoff. Corporate
endpoint policy, live proxy/CA connectivity and binary redistribution are not certified.

## Prior revision — credential-mask lifecycle (2026-10-05)

Version **0.1.1.dev9** adds bounded process-local masking across credential changes,
late outputs and continued conversations, with atomic capacity rejection and distinct
current authentication. Synthetic regressions and registry benchmarks are detailed
below. The real Windows Edge flow adds historical-state, clipboard and text-export
checks through actual loopback APIs. Exact-head six-job results and artifact hashes
belong to the draft PR handoff; no live inference or binary distribution is implied.

## Prior revision — strict web text decoding (2026-10-05)

Version **0.1.1.dev8** adds strict declaration-aware text decoding with actual codec,
selection-source and UTF-8-assumption metadata. Pure fixtures cover supported codec
families, BOM/header/meta/XML/JSON precedence, malformed declarations and bytes,
raw/inert HTML decoys, Unicode label normalization, NUL-interleaved JSON, response
privacy and exact cleaned-output bounds. A real local proxy covers redirect/header/
CP932 integration without a third-party connection. Frozen-EXE acceptance additionally
exercises every supported codec family through a fixed loopback proxy that never
forwards to the requested numeric public address. This checks actual packaged codecs.

The meta scan is deliberately conservative and stops at the first raw/inert element;
strict decoding is not source-fidelity verification or full browser compatibility.
The existing network transport/security tests and all prior UI acceptance assertions
remain. Final exact-head six-job CI, artifact hashes and Windows evidence are reported
in the draft PR handoff. No live model service, corporate-PC connectivity or binary
redistribution clearance is implied. See [the versioned cycle record](DEVELOPMENT_LOG.md).

## Prior revision — truthful state v1 (2026-10-05)

Version **0.1.1.dev2** adds real assignment display/search, runtime-derived waiting reasons
and shared snapshot/POST reply eligibility. New regression cases cover redaction and JSON
serialization, unchanged original briefs, human follow-ups during active inference,
question/error/mixed waiting, and non-mutating rejection for stale settings and hard
limits. The real Edge flow additionally checks turn-budget and stale-setting recovery
screens at desktop/narrow sizes. See the cycle 2 development record for adopted/deferred
ideas. Final head-specific results are reported in the PR handoff; no live-model quality,
real-user desktop, GPU, proxy or complete accessibility audit is implied.

## Prior verified revision — browser acceptance v1 (2026-10-05)

Version **0.1.1.dev1** adds a Windows Edge browser job and corrects narrow-layout
clipping found by inspecting its actual screenshots. The implementation at
`c8e4f510b120593a8c9a3f5ca84aa68803910781` passed all five jobs in
[run 37259569652](https://github.com/tyama-ds/agent-workbench/actions/runs/37259569652):
Windows/Ubuntu × Python 3.11/3.13 plus real Edge 153.0.4234.48. The report records
tested PR merge SHA `4ac18ba28dd759ba0907ee142106f2134a2b1036`, distinct from the source
head above. Windows Python 3.13: 281 passed, 1 symlink-privilege skip.
[Eight screenshots and the assertion report](https://github.com/tyama-ds/agent-workbench/actions/runs/37259569652/artifacts/11323354158)
are retained until 2026-10-19; downloading requires repository access. Local suite:
**278 passed, 4 Windows-only skips**, with dependency consistency and JS syntax checks.

The completed browser flow covers 1366×768 desktop, 820×768 tablet and 390×844 narrow
layouts, long Japanese questions, visible stop notice, modal keyboard/Escape behavior,
per-agent drafts and real HTTP/engine question/reply/mail/cancellation. All page-error,
CSP-error and external-page-request lists were empty. Current PR checks must also pass
for later commits; this dated run is evidence for the named implementation, not a claim
that an untested future revision passed. Browser claims farther below are historical.

The browser flow uses isolated temporary state. Its first phase uses contract-checked
synthetic UI snapshots; its second uses real HTTP endpoints and the real engine with an
injected deterministic model client. Neither phase invokes a live model service.
Reports explicitly label synthetic data and record browser version. Artifacts contain
only `workbench-*.png` and `browser-smoke.json`, not traces, HAR, session cookies or state.
Screenshots support human review; this is not a pixel-baseline comparison suite. Full
screen-reader and browser/text-zoom audits have not been performed.

Local reproduction (Node 22+ is needed only for this developer check):

```
npm ci --prefix tools/browser-tests --ignore-scripts --no-audit --no-fund
# Windows PowerShell; after normal Python dependency setup:
$env:WORKBENCH_TEST_PYTHON = (Get-Command python).Source
node tools/browser_smoke.cjs
```

Windows uses installed Edge. Other developer hosts may set
`WORKBENCH_BROWSER_EXECUTABLE` to an installed Chromium executable. The application
itself still requires no Node or browser-test dependency. See
[the versioned cycle record](DEVELOPMENT_LOG.md) for scope, research and limitations.


Local verification date: 2026-10-01. Environment: Windows, Python 3.13, Edge headless for UI tests.

Recorded local result after adding the automatic collaboration budget: **159 passed, 1 skipped**. The initial setup also passed `pip check`, ran successfully through Windows PowerShell 5.1 and created the desktop shortcut. A separate launcher smoke test verified a Japanese/spaced state path and duplicate-launch handling without interrupting the running fixture server.

## Automated checks

`python -m pytest -q` verifies the following using temporary folders and local HTTP fixtures:

- Three provider protocols, structured tool arguments, native reasoning replay, credentials not following redirects, bounded responses/retries and Local proxy bypass.
- Global Local concurrency, queue timeouts, start intervals, GPU admission behavior with synthetic readings, cancellation slot release, and remote GPU-monitor refusal.
- Actual Engine + actual HTTP adapters: OpenAI PM creates two Local/Qwen workers and an Anthropic worker, three Office files are written and re-read, worker completion automatically wakes PM to finish. Peak Local requests stay at one while three workers exist and cloud work overlaps.
- Actual Engine stop during a delayed write: stop remains in progress, the shared lock and reservation remain held, write completion is drained, then no further model request starts.
- Folder boundaries, denied roots, traversal/device/ADS paths, hardlinks, real Windows junctions, read/write independence, optimistic write conflicts, Office round trips, package external references/macros/DDE/formula restrictions and ZIP/XML limits.
- Real HTTP proxy fixture receives both search and fetch; environment proxy variables are ignored, private redirects and unsafe IP families are refused, and decompressed response sizes are bounded.
- Browser bootstrap expiry/one-use policy, Host/Origin checks, CSP, JSON-only mutations, memory-key persistence boundary, chunked models-list parsing, and active-run settings lock.
- Agent budget/role restrictions, cross-team mail rejection, pause/finish suppressing later calls, human FIFO, secret snapshot redaction and reservation conflicts.
- Automatic collaboration default/migration (24), configurable bounds (0–1000), counting successful assignments/mail/completion/error notices, failed-delivery exclusion, atomic competing sends, exact-limit completion, zero-budget batch suppression, successful worker results when notification is blocked, and no budget reset after human input.
- Windows installer proxy handling passed 17 focused checks using the real PowerShell 5.1 script and a temporary command stub that records arguments instead of downloading packages. This covers both pip stages, inherited proxy settings, explicit proxy/CA/timeout options, paths with spaces, invalid-option rejection and preservation of an existing environment after installation failure. It does not verify a user's corporate proxy credentials or network reachability.

The Windows symlink test can skip when the account lacks symlink creation privilege. Windows junction coverage is a separate test and is exercised. On hosts without Node.js, JavaScript syntax/unit tests skip; the UI runtime itself does not need Node.

`python -m pip check` verifies resolved dependency consistency. `requirements.lock` pins runtime and validation packages and includes PyPI SHA-256 release hashes. It is not a claim that all future vulnerabilities are known or that a dependency can never be compromised.

`python tools/audit_dependencies.py` checked PyPI's known-advisory records for all 25 locked distributions on the verification date: no active advisories were returned. This only reports that source's known records for those exact versions; it does not replace code review or ongoing dependency maintenance.

## Browser acceptance

`tools/browser_smoke.cjs` starts a separate real app instance on a random port with temporary state, uses a real `/models` fixture, and opens Edge. It verifies bootstrap, configuration persistence, memory-only secret entry, exact text submission, role cards, mail, human answers, stopped state, settings lock, default collapsed reasoning, desktop/mobile layout and no HTML injection. Team snapshots here are synthetic UI fixtures; engine behavior is covered independently by the HTTP integration tests above.

Screenshots and the report are generated under ignored `runtime/verification/`. The automatic collaboration setting was checked from default 24 through edit/save/reload at 7; live counters and a blocked-handoff notice were also exercised. The tested browser page made no external asset/network requests and had no JavaScript or CSP errors.

## Not yet verified with real services

- Real OpenAI/Anthropic account access, billable inference, rate limits and every model-specific parameter combination.
- An actual installed Local model's tool-use quality, context window, server chat template/parser and throughput.
- Physical GPU admission behavior on the target inference installation; GPU logic is tested with deterministic readings. Remote GPU monitoring and hard VRAM enforcement are unsupported.
- Complete preservation/rendering of complex Office layouts, protected documents, legacy binary formats, or Excel formula recalculation.
- Hostile same-user OS-level isolation and all possible third-party document parser vulnerabilities.

These distinctions are intentional: no live API credentials were supplied for validation, and no paid inference was performed by the tests.

## Corporate Windows installer revision (2026-10-04)

Local verification for this revision used Linux / CPython 3.12.14, not a Windows desktop:

- Full suite: **206 passed, 4 skipped**. Windows CMD, PowerShell 5.1, mutex/duplicate-launch and junction checks require Windows and are not covered by this Linux result.
- Fresh actual offline install from a hash-checked local wheelhouse, repeated install, `pip check` and application/Office module imports passed.
- All 25 locked distributions could be downloaded as Windows x64 CPython 3.13 wheels with `--only-binary=:all:` and `--require-hashes`.
- Independent real launcher smoke used a dynamic port and a Japanese/spaced state path; `/`, `/app.js`, `/styles.css` returned HTTP 200 and the server exited cleanly.
- Installer unit tests cover preflight/no-install mode, missing files, write failure, retained incomplete/reused environments, rejected interpreter variants, proxy/CA argument validation, stage failure propagation, hash/binary-only flags, post-install checks, offline pip-option isolation and rejection of redirected/extra online pip inputs. No corporate proxy passwords or live API keys were used.

The Windows matrix now includes real CMD and PowerShell wrapper checks, duplicate launch, plus clean and repeated offline installation on Python 3.11 and 3.13. Until those CI jobs run successfully, these added Windows checks are **unverified**. This does not validate a particular company's AppLocker/WDAC rules, proxy authentication or CA configuration. The earlier Windows result above records the previous installer, not proof that the new CMD route has run on Windows.

## File mutation protection revision (2026-10-05)

Verified locally on Linux / CPython 3.12.14 after the cockpit revision:

- Full suite: **273 passed, 4 skipped**. The four Windows-only checks (junction, CMD, PowerShell 5.1 and mutex/console process group) remain unverified here.
- Text creation/replacement/patch now validate output and the original locked/hash-checked snapshot. Regressions cover invalid UTF-8, NUL, binary controls, renamed ASCII PDF/GIF/container signatures, known format extensions (including new/empty files), patch removal of an entire signature, original-byte preservation, write-only permissions, UTF-8 BOM/CRLF/Japanese, empty and ordinary CSV/JSON/SVG/extensionless files.
- External edits between temporary write and publication still fail the final hash check; simulated atomic replacement failure preserves the original and removes temporary files. Existing path/deny/link and Office package tests pass.
- SearXNG configuration tests verify LAN HTTPS requirements and the exact HTTP loopback exceptions. No network/proxy/TLS behavior was weakened.
- `pip check`, JavaScript syntax checks for the app and both smoke scripts, `git diff --check`, and the optional jsdom DOM smoke all pass. No GUI or Windows setup implementation was changed.
- Independent review additionally passed 34 synthetic file-boundary/race checks. This conservative known-format guard is not a universal file-format classifier; keep important originals read-only.

The DOM smoke uses simulated dialog APIs and is not visual/browser acceptance. Real browser rendering and real Windows execution were not rerun for this file-safety-only revision; the limits recorded in `GUI_REDESIGN.md` still apply. No live model services, user-PC changes, GitHub push, merge or release were performed.

## Current-session results revision (0.1.1.dev3)

Local Linux verification: **312 passed, 4 Windows-only checks skipped**. Added tests cover
actual receipts for all seven writing tools, create/update identity, failed-write
exclusion, write-only isolation, bounded/redacted retention, terminal replies versus
intermediate narration, resumed response history, idle PM replies, and successful or
failed cancellation-drained writes. Observer failure does not change saved-file success.
Frontend tests cover text-only rendering/export, omissions, historical status,
selection preservation, latest-request clipboard feedback and failed-download cleanup.
`pip check`, JavaScript syntax, compileall, `git diff --check` and the optional jsdom
smoke pass. DOM shims are not browser rendering evidence.

The Edge acceptance script additionally checks actual engine-produced save receipts and
terminal answers, native clipboard copy, downloaded UTF-8 text, repeated exports,
selection races, pending-copy rejection, draft retention and desktop/narrow layouts.
Local Chromium could not start under this container's socket restriction, so these real
browser assertions require the exact-head Windows Edge CI run and its screenshots.
No real model service, billable inference or private user files are used.

## Run readiness revision (0.1.1.dev4)

Local Linux/CPython 3.12 verification: **453 passed, 4 Windows-only checks skipped**.
`pip check`, JavaScript syntax, `git diff --check`, and optional jsdom smoke pass.
Mocked diagnostics cover bounded/chunked bodies, strict JSON/schema validation,
HTTP/network/TLS errors, redirects, pagination, manual aliases, output truncation,
and credential echoes. Admission tests exercise preflight/start parity, PM-only
unused workers, empty/denied/missing roots, unusable environment keys, Web state,
potential destinations, and repeated no-network/no-state-change checks.

Windows Edge acceptance adds saved-vs-unsaved setup, exact admission recovery,
manual aliases, profile/selection/navigation late-response races, desktop/narrow
scope previews, and PM-only text work while preserving prior results and drafts.
This browser evidence requires the exact-head CI artifact; DOM shims are not visual
verification. No installed model, paid inference, external scan, user PC, or corporate
network configuration is exercised by these synthetic tests.

The first cycle-4 Edge run exposed a real textarea-blur/click race: redundant preflight refresh moved the Start button during a pointer action. The fix deduplicates unchanged payload/configuration previews, retains pending content, visibly marks pending checks, preserves expanded scope details, and defers preview layout changes through native Start pointer gestures. The exact failing narrow-screen click remains in acceptance coverage; fresh final-head CI is required after the fix.

## Experimental ONEDIR revision (0.1.1.dev5)

The portable CI job is separate from source-install validation and depends on the full
source/Edge jobs. It uses official CPython 3.13 x64 on Windows and a fresh, hash-locked
build environment. A successful freezer exit is insufficient: the development-only
acceptance driver extracts the ZIP to Japanese/space/punctuation paths, verifies its
checksum and manifest, launches the production EXE with a minimal system-only PATH,
and supplies a deterministic loopback HTTP model through the real provider adapter.
Office create/read/edit, real save receipts, result rendering, path exclusions,
authentication and duplicate/port behavior are evaluated internally. No binary artifact upload is configured.

The driver and CI build tools can use Node/Python; the application child cannot rely
on them through its PATH or Python environment. No test model client or HTTP test route
is added to the production app. Windows native Job lifecycle, output caps and utility
timeouts have additional platform tests. GPU hardware and arbitrary company policy
configurations are not established by a hosted runner.

The build manifest explicitly says its own builder has not performed acceptance.
Consult the exact commit's CI report/artifact for that separate evidence. An artifact
checksum identifies bytes; it is not code signing or a corporate trust decision.

The native redistribution review is unresolved. Evaluation-only mode explicitly
records that blocker and incomplete interpreter-native notice/provenance review; it
does not weaken available-file checksum checks or establish distribution readiness.
Both success and failure uploads use an explicit non-binary evidence allowlist.

## Selected-detail polling revision (0.1.1.dev6)

The unchanged full endpoint and the new selected endpoint are measured through a
real authenticated loopback HTTP server by `python -m tools.benchmark_state`.
Fixtures use the repeating seven-character text `調査abcde`, empty thinking,
160-character tasks/assignments/events, and a private 20,000-character conversation
per agent. Agents are done, not stopped, with turn 10 below limit 100 and a frozen
fresh creation clock below the 86,400-second budget. Both projections therefore
perform real conversation eligibility serialization; no earlier blocker skips it.
Receipts are deterministic synthetic metadata. No model client is constructed.

Measured on local Linux/CPython 3.12, seven warmed repetitions per operation:

| Fixture | Full body bytes | Selected body bytes | Reduction | Snapshot ms, full / selected | JSON ms, full / selected | HTTP ms, full / selected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Small: 1 run × 3 agents; each 40 logs × 400 chars, 2 reports × 2,000 chars, 4 receipts; 60 events | 190,294 | 84,795 | 55.440% | 3.302 / 1.420 | 0.331 / 0.158 | 4.541 / 2.609 |
| Medium: 5 runs × 5 agents; each 120 logs × 800 chars, 10 reports × 6,000 chars, 24 receipts; 500 events | 10,143,889 | 465,882 | 95.407% | 60.184 / 6.992 | 27.120 / 1.110 | 117.619 / 8.707 |
| Report cap: 1 run × 5 agents; each 200 logs × 800 chars, 20 reports × 24,000 chars, 64 receipts; 200 events | 8,037,187 | 1,639,950 | 79.595% | 17.494 / 4.731 | 13.611 / 2.475 | 51.811 / 9.628 |

Body sizes are actual uncompressed JSON response bytes, including aiohttp's default
ASCII escapes, excluding headers/TCP. Snapshot time includes fresh metadata,
eligibility and redaction; JSON time serializes a prebuilt projection and excludes
UTF-8 encoding. HTTP timing includes projection/serialization and full response
read, excluding JSON parsing or browser rendering. Medians are independent samples,
not values that must sum. The standalone CLI applied a 256 MiB virtual address-space
ceiling, not a claim that it measured peak memory. These bounded synthetic results
are not global worst-case or Windows production-performance guarantees. Slight byte
differences from the earlier planning estimates reflect fixed reproducible fixtures.

Regression coverage includes selected/full field parity, omitted-history traversal
sentinels, event filtering before the visible limit, redaction, unchanged default
API/authentication/no-store, time-only eligibility transitions, explicit loading,
deferred selection ownership, and DOM stability. Windows Edge acceptance must run
against the exact published head; local Chromium launch in this container was blocked
by its socket restrictions, including after an approved launch attempt. DOM shims
are not a substitute for browser layout evidence.

Local aggregate: **549 passed, 6 Windows-only skips**, plus dependency consistency,
JavaScript syntax, whitespace and optional DOM smoke. Independent review additionally
ran focused API and deferred-frontend suites without a source blocker. The Windows
browser job also records its own bounded benchmark JSON beside screenshots; consult
that exact-head artifact rather than extrapolating the Linux timing table.

## Configured-model attribution (0.1.1.dev7)

`test_configured_profiles.py` covers immutable descriptors across reused IDs,
renames, disabling/deletion, mixed providers, full/compact parity, independent public
copies, missing metadata, stale-config reply rejection, and secret-reference deletion
before later worker creation. Frontend assertions cover poll-stable roster nodes,
unknown/malformed metadata, explicit ownership and JSON-quoted export names/model IDs.
The Edge acceptance script edits and removes a real saved profile after actual
synthetic engine runs, starts a new configured-model run, and verifies old report and
receipt exports stay byte-identical. New desktop/narrow attribution screenshots must
be reviewed with the exact-head report. No server alias or live API is verified.
## Credential-mask lifecycle revision (0.1.1.dev9)

Synthetic regressions cover memory replacement/removal, environment-reference and
provider identity changes, old and newly recognized retained text, late replies,
thinking/errors/receipts/diagnostics, completed-run continuation, full/selected/
summary projections, atomic count/UTF-8 saturation and fixed safe error branches.
Request recorders verify current auth with stable in-flight headers, current search
credentials with frozen run destinations, and no stale memory-key inheritance when
IDs or credential destinations are changed. No real keys or model APIs are used.

The normal `python -m tools.benchmark_state` report retains its original fixture
results and adds small-fixture registry measurements with four and 511 short values.
These stress distinct-count lookup work, not maximum credential payload. The opt-in
`python -m tools.benchmark_state --adversarial-redaction` uses 512 values occupying
exactly 2 MiB: 511 near-4-KiB shared-prefix strings and one different-prefix string.
It records registration, 24-KiB near-match masking, exact-match masking and whole-
process peak RSS where available. A local Linux/CPython 3.12 run under a 256-MiB
virtual-memory ceiling observed approximately 1.7 ms registration, 22 ms near-match
masking and 35 MB peak whole-process RSS. These are synthetic observations, not a
worst-case production-throughput or total-registry-memory guarantee.

On the same local run, the four-value small fixture measured full/selected projection
medians of approximately 0.76/0.46 ms; the 511-value fixture measured 30.50/16.98 ms.
Authenticated HTTP medians were 1.81/1.42 ms and 31.16/18.15 ms respectively. Values,
fixtures and initial-registration exclusions are recorded in the benchmark JSON.
The additional masks have measurable cost; selected-state work remains proportional
to the selected retained histories rather than all agents' heavy records.

Independent review additionally compared 5,000 deterministic overlapping/literal
cases against the intended leftmost-longest semantics. The previous regex candidate
failed the mixed-prefix timeout probe and was removed; it is not the released design.

Actual Windows Edge acceptance exercises credential replacement and environment-
reference changes through real loopback APIs, synthetic response continuations,
full/selected responses, UI text, clipboard and downloaded report/receipt attribution.
Consult the exact-head CI JSON/screenshots for results. The evidence-only artifact
allowlist remains unchanged; no packaged binaries are uploaded.

## Start/Stop response ownership (0.1.1.dev11)

`test_run_action_frontend.py` exercises the actual registered callbacks with a
deferred synthetic transport: accepted creation across failed/missing observations,
state arriving before the POST response, first-run selection, independent dialog,
draft and settings A → B → A generations, explicit retries, unknown and malformed
responses, per-run Stop guards across polls, concurrent Stops, changed terminal
states, target-labelled notices and retained draft/focus. It also calls the real
`api()` function against synthetic timeout/HTTP/malformed-JSON responses.

The separate `lifecycle_acceptance.cjs` phase uses real Windows Edge DOM actions and
routed synthetic responses. It checks pointer and keyboard submissions, delayed
responses and state failures, regular-poll recovery without replay, dialog/draft/
navigation ownership and Stop eligibility, and records desktop/narrow screenshots.
The existing real loopback Engine, authentication, receipts, stop-draining, settings,
privacy and model-attribution phases still run afterward. No live model is called.

An accepted run ID is held only in this page's memory. Unknown creation responses
are not turned into proof of rejection. There is no durable operation queue, server
idempotency key, automatic creation retry or cross-reload exactly-once guarantee.
Final full-suite, exact-head Windows and screenshot results are recorded in the
cycle handoff; DOM-only tests do not establish actual browser layout or focus.

## Saved-destination credential recovery (0.1.1.dev12)

`test_credential_recovery.py` exercises authenticated real loopback requests with
synthetic credentials: missing/malformed/stale revision rejection, a request whose
JSON body is delayed across a settings change, endpoint/proxy/kind/env/ID-reuse/ABA
ownership, provider/search isolation, unusable search destinations, unchanged failed
save/capacity revisions, and explicit same-run recovery. Replacement cannot bypass
model, turn, time, context, stop or changed-settings reply eligibility.

`test_credential_recovery_frontend.py` calls the actual registered callbacks with
synthetic DOM/deferred transport. It covers saved-target-only enablement during
waiting runs, focused-input stability through polling, dirty/new guards, per-target
concurrency and save locking, unknown/malformed receipts, close/reopen ownership,
GET-only discard, complete draft preservation and search applicability.

`credential_recovery_acceptance.cjs` adds real Windows Edge keyboard/native control
coverage using the real loopback server and synthetic authentication-error fixture.
It exercises dirty/error recovery, discard without settings PUT, independent target
requests, delayed real acceptance/rejection, unchanged budgets/settings, and explicit
same-agent continuation. Desktop/narrow screenshots and no-external-request checks
join the existing evidence-only artifact allowlist. The new stage must pass on the
exact candidate head; syntax checks or fixture HTTP tests are not browser evidence.

## First-task capability guidance (0.1.1.dev13)

`test_task_guidance.py` verifies that the textarea's accessible description resolves
outside the optional native disclosure, the essential execution limit is persistent,
three examples are static and non-interactive, and file/Web prerequisites agree with
the unchanged tool boundary. A synthetic local preflight confirms the text-only
example needs neither file roots nor Web and starts no run or inference. These are
source/contract checks, not browser or model-quality evidence.

`first_task_acceptance.cjs` exercises the real Windows Edge native disclosure through
keyboard interaction. It checks visible guidance after typing, unchanged task and
profile selections across preflight/settings/close/reopen, and no hidden mutation or
provider request. Collapsed/expanded desktop, tablet and narrow screenshots accompany
geometry assertions, including reaching lower controls by ordinary dialog scrolling.
Existing delayed-preflight, Start/Stop ownership, credential recovery and actual
Engine flows remain in the same acceptance run. Exact-head artifact reports and
independent pixel inspection are required before this cycle is called complete.


## Contextual history lifetime guidance (0.1.1.dev14)

- Static semantics: essential lifetime note is outside disclosures; optional detailed
  help has no mutation handler; export help describes one selected record and excludes
  file contents. Existing model-report/current-file warnings remain unchanged.
- Synthetic admission: 20 mixed completed/stopped runs remain intact after 21st-run
  preflight and Start rejection; no eviction, budget reset or additional model call.
  Closed-engine and full-history explanations are distinct with the same error code.
- Real loopback lifetime: page GET and same-cookie reconnect preserve exact run/agent
  data; absent-cookie reads and replayed bootstrap remain rejected without clearing
  history. Team Stop retains reports, receipts, memory key and written bytes. Server
  cleanup clears memory-entered keys; a fresh app at the same state directory restores
  settings and environment-key lookup, starts with no histories, and leaves the actual
  saved file unchanged. Only settings.json is persisted in the state directory.
- Windows Edge: actual synthetic retained reports/receipts survive reload and closing
  and reopening a tab in the same browser context. Compare IDs, call counters, output
  files and configuration; maintain instrumentation on every added page. Optional help
  and ordinary polling must not issue new mutations, inference or downloads.
- Desktop/tablet/narrow evidence checks visible warning, native disclosure keyboard,
  selected record, result-panel and run-list reachability, focus/scroll preservation,
  explicit single-record exports and no horizontal/sidebar overlap. No assertion of
  full browser-restart recovery, crash durability, assistive-technology certification
  or access to a saved file merely because its receipt is retained.
