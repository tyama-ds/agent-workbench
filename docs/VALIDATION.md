# Validation scope

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
