# Validation scope

## Current revision — truthful state v1 (2026-10-05)

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
