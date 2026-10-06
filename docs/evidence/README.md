# Verification evidence index

Current policy from **0.1.1.dev23** is source-only installation with separately
approved Python. Bundled builds and their CI job are discontinued. Historical
portable reports below remain records of their named commits, not active build or
distribution instructions.

Use the [live draft PR #2](https://github.com/tyama-ds/agent-workbench/pull/2) for
verification of its explicitly named current head. A passing run or screenshot review
for an older source commit does not accept a later commit, even when code is unchanged.
Application behavior and test scope are described in [VALIDATION](../VALIDATION.md);
research, adopted/deferred decisions and corrections are in the
[development log](../DEVELOPMENT_LOG.md). See [SECURITY](../../SECURITY.md) for boundaries.

## Frozen public PR snapshot

- [Full PR description captured 2026-10-05](pr-2-2026-10-05.md), covering cycles 1–17.
- [Machine-readable provenance and all 56 original public URLs](pr-2-2026-10-05.json).
- Source head: `52694374090c89981657af2970694874b95b5191`, version `0.1.1.dev17`.
- Source PR last updated: `2026-10-05T11:47:49Z`; captured: `2026-10-05T11:50:41Z`.
- Original body: **63,437 characters / 63,502 UTF-8 bytes**, without a final newline.
- SHA-256: `bd8e946e5e261cdd25f598cf9d599a339521009ca20e8d7ae25973a6a2d85299`.

The full original body is preserved byte-for-byte after its archive marker. The
manifest gives the UTF-8 byte offset, length and hash, plus every URL in original
order. No original claim, failed-attempt explanation, limitation, source/run/artifact
link, artifact digest or historical review note was removed. The archive is a record
of the public description, not an independent revalidation of its statements.
Its original **“Current verification” means the captured dev17 source head only**.

## Historical cycle navigation

| Cycle | Subject | Original verification record |
| --- | --- | --- |
| 27 | Protected displayed-task reuse drafts | [Complete prior compact PR overview](dev27-task-reuse-verification.md) and [exact-body provenance](dev27-task-reuse-verification.json) |
| 26 | All-session human questions and safe reply navigation | [Complete prior compact PR overview](dev26-questions-verification.md) and [exact-body provenance](dev26-questions-verification.json) |
| Docs 1 | Internal deployment review checklist | [Complete preceding public overview](docs-revision1-it-review-verification.md) and [exact-body provenance](docs-revision1-it-review-verification.json); source `59d26a962f9f03a24bf0a6f7153b635450921cf9` |
| 25 | Python-independent CMD setup help | [Complete prior compact PR overview](dev25-setup-help-verification.md) and [exact-body provenance](dev25-setup-help-verification.json); [validation scope](../VALIDATION.md#python-independent-setup-help-011dev25-2026-10-06) |
| 24 | Data-use guidance and Local/LOCAL APP limits | [Complete prior compact PR overview](dev24-data-use-verification.md) and [exact-body provenance](dev24-data-use-verification.json) |
| 23 | Source-only setup with separately approved Python | [Complete prior compact PR overview](dev23-source-only-verification.md) and [exact-body provenance](dev23-source-only-verification.json); [current installation policy](../WINDOWS_SETUP.md) |
| 21 | Terminal batch precedence and reachable-session regressions | [Complete prior compact PR overview](dev21-transitions-verification.md) and [exact-body provenance](dev21-transitions-verification.json) |
| 20 | Revision-owned settings saves and retained drafts | [Complete prior compact PR overview](dev20-settings-verification.md) and [exact-body provenance](dev20-settings-verification.json) |
| 19 | Poll-stable keyboard disclosure focus | [Complete prior compact PR overview](dev19-keyboard-verification.md) and [exact-body provenance](dev19-keyboard-verification.json) |
| 18 | Hash-bound native notice/provenance evidence | [Prior dev18 verification, including retry history](dev18-native-evidence-verification.md) |
| 17 | Queued filesystem deadline checks | [Captured dev17 verification](pr-2-2026-10-05.md#current-verification) |
| 16 | Provider completion evidence and Local refusals | [Cycle 16 verification](pr-2-2026-10-05.md#historical-cycle-16-verification) |
| 15 | Truthful tool-result recovery | [Cycle 15 verification](pr-2-2026-10-05.md#historical-cycle-15-verification) |
| 14 | History lifetime and safe restart | [Cycle 14 verification](pr-2-2026-10-05.md#historical-cycle-14-verification) |
| 13 | Truthful first-task guidance | [Cycle 13 verification](pr-2-2026-10-05.md#historical-cycle-13-verification) |
| 12 | Saved-destination memory-key recovery | [Cycle 12 verification](pr-2-2026-10-05.md#historical-cycle-12-verification) |
| 11 | Start/Stop response ownership | [Cycle 11 verification](pr-2-2026-10-05.md#historical-cycle-11-verification) |
| 10 | Contained corporate setup | [Cycle 10 verification](pr-2-2026-10-05.md#historical-cycle-10-verification) |
| 9 | Bounded credential-mask lifetime | [Cycle 9 verification](pr-2-2026-10-05.md#historical-cycle-9-verification) |
| 8 | Strict web text decoding | [Cycle 8 verification](pr-2-2026-10-05.md#historical-cycle-8-verification) |
| 7 | Historical configured-model attribution | [Cycle 7 verification](pr-2-2026-10-05.md#historical-cycle-7-verification) |
| 6 | Selected-detail polling | [Cycle 6 verification](pr-2-2026-10-05.md#historical-cycle-6-verification) |
| 5 | Evaluation-only Windows ONEDIR | [Cycle 5 verification](pr-2-2026-10-05.md#historical-cycle-5-verification) |
| 4 | Local preflight and model diagnostics | [Cycle 4 verification](pr-2-2026-10-05.md#historical-cycle-4-verification) |
| 3 | Model reports and actual save receipts | [Cycle 3 verification](pr-2-2026-10-05.md#historical-cycle-3-verification) |
| 2 | Assignments, attention and recovery | [Cycle 2 verification](pr-2-2026-10-05.md#historical-cycle-2-verification) |
| 1 | Windows Edge browser acceptance | [Cycle 1 paragraph at end of cycle 2](pr-2-2026-10-05.md#historical-cycle-2-verification) |

Cycle 1's final run and artifact links were originally nested at the end of the cycle 2
verification section. Earlier corrective attempts and research citations also remain
in the development log; this index does not substitute a different run for acceptance.

## Evidence lifetime and limits

CI JSON/PNG artifacts have **14-day retention**; the captured description records
**2026-10-19** expiry. URLs and reported digests remain here after downloads expire,
but this repository snapshot does not preserve screenshot/report bytes or extend
retention. The artifact ZIP digests identify evidence archives, not distributable
application packages. Availability and contents must be checked before reusing them.

Python bundling is **discontinued**. The former Windows ONEDIR job was evaluation-only
and is now removed. No EXE, DLL or application ZIP is uploaded by current CI. Passing synthetic loopback providers,
Windows runner setup and Edge acceptance does not establish live-model behavior,
corporate-PC/proxy compatibility, GPU behavior, legal clearance, a full accessibility
audit or a hard deadline for already-running I/O. See the original records for each
cycle's narrower claims and failures that preceded the accepted run.

## Keeping the live overview useful

Keep the PR description focused on current scope, named source/merge SHAs, fresh CI
and evidence, blockers, and links to versioned documentation. Replace the current
verification summary when the head changes; never relabel historical checks as fresh.
Retain this snapshot unchanged. If a later archive is needed, add a separately dated
snapshot and provenance manifest rather than duplicating the whole history in the PR.
Document-only commits still need their own exact-head check results before being
called verified; a copied archive is not a new application feature or version.
