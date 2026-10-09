# Historical dev26 all-session questions verification

This is the complete preceding PR #2 overview captured before dev27. Its
“current” claims apply only to source 932371cead34aeb896f9b4e5abb3c44111c01502.
It is preserved as historical evidence, not acceptance of a later commit.
The body after the marker is byte-for-byte the fetched public PR description.

<!-- BEGIN ORIGINAL PR BODY -->
## Scope
Stacked on draft PR #1 (`fix/orrery-inspired-cockpit`). Version **0.1.1.dev26**, based on verified source-only head `59d26a962f9f03a24bf0a6f7153b635450921cf9`. Keep the ORRERY-inspired cockpit, separately approved Python, current permissions, dependencies and five-job CI.

## All-session human questions
- Extend the existing header toggle and left roster to show human-input pauses across all retained teams. Global and filtered counts stay distinct; session rows also show question counts.
- Show a separate visible team ID, task, agent, question preview, starting profile and current reply availability. Questions with blocked/unknown eligibility remain discoverable. Errors, teammate waits, blank questions and stopped residue are excluded.
- Opening a question atomically selects its exact team and agent. The center/right panels clearly retain the selected team’s log, results, map and activity. Opening, searching and polling never answer, resolve, resume or reset a budget.
- Preserve exact per-agent drafts and compact selected-detail ownership. Selection and draft epochs prevent delayed send responses from erasing or labeling a newer same-ID/same-text interaction.
- Retain native Tab/Enter/Space/pointer controls, keyboard-scrollable full questions, changed-count polite announcements, stable reading position and visible nearby/toggle focus fallback. No automatic focus movement on arrivals.
- No backend queue, endpoint, AI ranking, unread/resolution state, persistence, notification service, permission expansion or dependency is added. This is agent-scoped messaging, not a versioned-question approval system.

[README](https://github.com/tyama-ds/agent-workbench/blob/932371cead34aeb896f9b4e5abb3c44111c01502/README.md) · [architecture/state contract](https://github.com/tyama-ds/agent-workbench/blob/932371cead34aeb896f9b4e5abb3c44111c01502/docs/ARCHITECTURE.md) · [validation scope](https://github.com/tyama-ds/agent-workbench/blob/932371cead34aeb896f9b4e5abb3c44111c01502/docs/VALIDATION.md) · [research and adoption decisions](https://github.com/tyama-ds/agent-workbench/blob/932371cead34aeb896f9b4e5abb3c44111c01502/docs/DEVELOPMENT_LOG.md).

## Current dev26 verification
Source head: **932371cead34aeb896f9b4e5abb3c44111c01502**. Tree: **abe7749e34bb409cd6acd61314418545d6c01df8**. Sole parent: **0b9bcf0be9f67c09de9296e6dfb31fec93a33e91**. PR merge: **ec75fc829c9aad70195abfb3b6d48f1815e3009b**.

Final local aggregate: **1248 passed, 42 platform-specific skips**, independently repeated on the reviewed candidate. Dependency consistency, compilation, JavaScript syntax and whitespace checks pass. Five existing state-benchmark cases make zero model calls and retain one selected agent history per compact response. Optional local DOM smoke is unavailable because jsdom is absent; no dependency was installed.

Independent source review approved the exact 19-file tree, integration contracts and preserved history. All 19 published blob hashes and complete tree match the reviewed local candidate. Engine/HTTP tests exercise running-team pauses, non-mutating global discovery, clock-only expiry, rejected replies and explicit reply/stop transitions. New browser acceptance covers 20 sessions, long Japanese source/question text, native pointer/keyboard interaction, draft/selection/send races and focus at desktop/tablet/narrow widths.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37398800128) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37398805830): **all five jobs passed on attempt 1** in both final-head runs. Independent log review verified actual source/merge checkout SHAs in all ten jobs. Each Windows matrix job reports **1289 passed, 1 skipped**; each Ubuntu job reports **1248 passed, 42 skipped**. All Windows offline repeated-setup, package consistency, explicit-interpreter preflight and launcher gates passed.

[Final source-bound Edge evidence](https://github.com/tyama-ds/agent-workbench/actions/runs/37398800128/artifacts/11384412505) and [PR Edge evidence](https://github.com/tyama-ds/agent-workbench/actions/runs/37398805830/artifacts/11384069237) each contain **44 checks, 109 PNGs**, zero page/CSP/external-request errors and Edge **153.0.4234.48**. Both reports match their exact source/merge and run identities; both ZIPs passed API-size/digest, CRC, 111 unique flat JSON/PNG-only member and extracted-byte checks. The source ZIP is **12,980,567 bytes**, SHA-256 **a5cff715d6101fff5240242e593032ea1b7d560756ff17ba5fbf841586ae822c**, expiring **2026-10-20**. Independent inspection of the five new exact-head question screenshots confirms visible Send controls, team provenance, card content and removal-fallback geometry at their tested widths. The source worktree is clean.

The [first source Edge pass](https://github.com/tyama-ds/agent-workbench/actions/runs/37397682207) on `f25f0ea` exposed real desktop Send/footer clipping with a long task and question. The failure screenshot was inspected independently. The corrective commit lets the bounded question region shrink to 52px while preserving keyboard scrolling, and adds stronger full-card geometry checks. The strict visibility gate is retained. The full local suite passed again; the fresh hosted acceptance results are recorded above.

The [second pass](https://github.com/tyama-ds/agent-workbench/actions/runs/37398218838) on `0b9bcf0` completed the new 20-session feature/geometry cases, then hit a legacy assertion requiring generic success feedback after editing the next draft. The final test correction holds the exact POST until after that edit, verifies HTTP acceptance and exact sent text, preserves the new unsent draft, and requires stale feedback to stay absent. Later cross-agent send cases remain unchanged. Runtime code is unchanged by this test correction.

## Historical acceptance
[Complete preceding documentation-revision overview](https://github.com/tyama-ds/agent-workbench/blob/932371cead34aeb896f9b4e5abb3c44111c01502/docs/evidence/docs-revision1-it-review-verification.md) and [exact-body provenance](https://github.com/tyama-ds/agent-workbench/blob/932371cead34aeb896f9b4e5abb3c44111c01502/docs/evidence/docs-revision1-it-review-verification.json) preserve **5299 characters / 5302 UTF-8 bytes**, SHA-256 **a94a0241da15e5cb6ae0a0f099f57a2dd8fdedee110353be32b2070bffc55993**, including all 11 original URLs. All 16 preceding evidence payloads remain byte-identical. [Evidence index](https://github.com/tyama-ds/agent-workbench/blob/932371cead34aeb896f9b4e5abb3c44111c01502/docs/evidence/README.md).

## Limits
Hosted synthetic checks do not establish corporate approval, corporate-PC/proxy compatibility, live-provider quality, downstream handling, GPU behavior or full accessibility conformance. No screen-reader user study is claimed. No live/billable inference, user-PC execution, merge, release, deployment or bundled binary is included. CI reports/screenshots retain their 14-day lifetime.
