# Historical dev28 PR overview

This is the exact preceding PR #2 description captured before the dev29–31 integration. Its test results apply only to the source and merge commits named below. Initial failures, bounded retries and screenshot limitations remain part of the record.

---

## Scope
Stacked on draft PR #1 (`fix/orrery-inspired-cockpit`). Version **0.1.1.dev28** preserves the cockpit, separately approved Python, permissions, dependencies and five-job source-only CI. Later local versions are not part of this head.

## Neutral message-input discovery
- **入力あり** marks on existing crew/question cards, per-session input-owner counts, and one explicit **全チームの次の入力へ** action.
- Count known owners with exact nonempty input, including whitespace and retained pending/unknown/accepted text. Presence does not establish an unsent message or current eligibility. Exclude the new-task editor.
- No input snippets in cards, search or status metadata. Missing owners are excluded without deleting or transferring their text.
- Traverse session-list and declared member order, selecting the exact team/agent once. Preserve both roster searches/modes and existing send/draft ownership. Same-owner activation only focuses the composer; blocked input opens its owner heading.
- Modal isolation, stale-detail/send ABA guards, stable typing/poll focus, presence-only DOM updates and immediate indicators after the existing successful clear.
- Concise card previews retain source IDs, neutral marks and availability; full content remains in selected detail. Real Tab/Shift+Tab reveals only the actual current roster-card focus target, with frame-time modal/DOM checks. Polling never schedules that reveal.
- No automatic send, replay, deletion, durable storage, new endpoint or attempt-state system.

[README](https://github.com/tyama-ds/agent-workbench/blob/39f38227adcb92d8d94cbfd67fe984c3900d553d/README.md) · [architecture](https://github.com/tyama-ds/agent-workbench/blob/39f38227adcb92d8d94cbfd67fe984c3900d553d/docs/ARCHITECTURE.md) · [validation](https://github.com/tyama-ds/agent-workbench/blob/39f38227adcb92d8d94cbfd67fe984c3900d553d/docs/VALIDATION.md) · [research and correction history](https://github.com/tyama-ds/agent-workbench/blob/39f38227adcb92d8d94cbfd67fe984c3900d553d/docs/DEVELOPMENT_LOG.md).

## Current verification
Source **39f38227adcb92d8d94cbfd67fe984c3900d553d**; tree **bab95d829136fb1d4c22dc2717218fbbc619ac45**; parent **efb482cd669202b85ce5e711802534de360b63e5**; PR merge **6177576a88d80431cee743d5f966c67bbc18a8c4**.

Final local full suite: **1,325 passed, 42 platform-specific skips**. Dependency consistency, 69 in-memory Python compilations, JavaScript syntax and whitespace pass. Independent production-source review and **28 focused presence tests** pass. Published blobs/trees match the reviewed local candidates; the exact-source checkout is clean.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37604758017) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37604765942): **all five jobs pass**. Independent review verified actual source/merge checkout IDs in all ten current job logs. Windows matrix jobs report **1,366 passed, 1 skipped**; Ubuntu jobs **1,325 passed, 42 skipped**. Offline repeated setup, package checks and the approved-interpreter launcher gates pass.

Both runs required one **failed-job-only retry on the same head**: first-attempt Windows 3.13 jobs hit existing 10-second Node subprocess timeouts in credential-reopen/completed-read fixtures. Those jobs passed unchanged on attempt 2. Successful jobs and Edge evidence retain their original executions; no timeout or assertion was relaxed.

[Source Edge artifact](https://github.com/tyama-ds/agent-workbench/actions/runs/37604758017/artifacts/11474646564) and [PR Edge artifact](https://github.com/tyama-ds/agent-workbench/actions/runs/37604765942/artifacts/11474482038) each contain **46 checks, 124 PNGs**, zero page/CSP/external-request errors, Edge **153.0.4234.48**, and five synthetic state benchmarks with zero model calls. Both ZIPs independently pass API-size/digest, CRC, 126 unique flat JSON/PNG member, every extracted-byte and exact report commit/run-ID checks.
- Source: **15,727,480 bytes**, SHA-256 **8adcd0b6a04723f08c5cfc29e00091380cdcd866c37e5d3f62b478e5e8fe8f4f**.
- PR: **15,729,069 bytes**, SHA-256 **22a532d24dbdfdac69801022210598838af75ee848a6d993f7e86a8f585cafe5**.
- Both expire **2026-10-21**.

Independent pixels accept all six new desktop/tablet/narrow crew/question views; corresponding PR files are byte-identical. Focused-question images are **viewport captures**. At every width, full-card/lower-action bounds, exact focus and scroll geometry remain unchanged before/after capture and after a real unchanged poll. Coverage retains 20 teams, real Tab/Enter/Space and enabled-pointer navigation, exact whitespace, blocked/missing owners, searches/modes, stale state/send responses and fixture restoration.

## Preserved corrections
The [development log](https://github.com/tyama-ds/agent-workbench/blob/39f38227adcb92d8d94cbfd67fe984c3900d553d/docs/DEVELOPMENT_LOG.md) retains all attempts and outcomes:
- [Initial run](https://github.com/tyama-ds/agent-workbench/actions/runs/37405818118): real desktop long-card clipping; fixed card density/scroll space, retaining strict bounds.
- [Second run](https://github.com/tyama-ds/agent-workbench/actions/runs/37406734628): test focus-style setup corrected to genuine Tab. [Third](https://github.com/tyama-ds/agent-workbench/actions/runs/37407490083) and [fourth](https://github.com/tyama-ds/agent-workbench/actions/runs/37408225451) established native narrow horizontal reveal failure; the keyboard-only reveal fixes it.
- [Resumed run](https://github.com/tyama-ds/agent-workbench/actions/runs/37601859460) passed CI but independent tablet pixels contradicted the immediate geometry check. The [capture diagnostic](https://github.com/tyama-ds/agent-workbench/actions/runs/37603649425) isolated full-page capture resetting the roster's 165px scroll position: real polls and viewport captures stayed correct. Final focused evidence uses viewport-only capture, with strict pre/post/poll geometry and no test-side scroll repair or production workaround.

## Separate follow-on
This discovery head preserves existing message acknowledgement semantics. Synthetic reproduction showed HTTP `200 {}` being accepted without requiring `{ok:true}`; strict receipt validation is recorded separately, not claimed fixed here.

## Historical acceptance and limits
The [complete preceding dev27 overview](https://github.com/tyama-ds/agent-workbench/blob/39f38227adcb92d8d94cbfd67fe984c3900d553d/docs/evidence/dev27-task-reuse-verification.md) and [manifest](https://github.com/tyama-ds/agent-workbench/blob/39f38227adcb92d8d94cbfd67fe984c3900d553d/docs/evidence/dev27-task-reuse-verification.json) preserve **6,949 UTF-8 bytes**, SHA-256 **a1b065366d094f56f42ad017031a2c7eaa2e40ba9e254c21b5d99dbdd7c91dc4**, including original failures, corrections and evidence links. All 20 older evidence payloads remain byte-identical. [Evidence index](https://github.com/tyama-ds/agent-workbench/blob/39f38227adcb92d8d94cbfd67fe984c3900d553d/docs/evidence/README.md).

Synthetic checks do not establish corporate approval, corporate-PC/proxy compatibility, live-provider quality, GPU behavior or full accessibility conformance. No live/billable inference, local browser retry, user-PC execution, new dependency, bundled Python, merge, release or deployment.
