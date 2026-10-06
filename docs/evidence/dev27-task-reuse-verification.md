# Historical dev27 verification snapshot

This is the complete preceding public PR overview for the captured dev27 source
head. Its current-verification claims apply only to that named snapshot, not to
dev28 or a later revision. Original wording, failed attempts, corrections and
URLs are retained byte-for-byte below. See the adjacent JSON manifest for provenance.

<!-- BEGIN ORIGINAL PR BODY -->
## Scope
Stacked on draft PR #1 (`fix/orrery-inspired-cockpit`). Version **0.1.1.dev27** preserves the ORRERY-inspired cockpit, separately approved Python, existing permissions/dependencies and five-job CI.

## Displayed request → protected new-task draft
- One selected-team action prepares a new task from only its last-displayed public request text. It never copies old conversations, results, models, credentials, permissions or budgets.
- Preserve current PM/worker/count selections. Different nonempty input, including whitespace, requires explicit Keep/Replace; identical text does not churn its draft epoch.
- Normalize only CRLF/CR to native textarea LF. Preserve remaining whitespace, literal markup and `[redacted]`; reject unavailable or oversized input without truncation at 16,000 UTF-16 code units.
- Bind replacement to raw displayed source, current form values and selection/navigation/dialog/workspace/draft epochs. Cancel source changes/removal, stale and ABA choices. Protect pending Start outcomes and existing agent drafts.
- Pending choices block Start and suppress/invalidate preflight. Adoption uses existing local admission-only preflight; creating a team remains an explicit separate Start. No automatic start/resume, model/tool work, mutation, persistence or new backend endpoint.
- Dedicated provenance/guidance describes displayed content and current saved settings. Native keyboard reading and existing cockpit layout remain.

[README](https://github.com/tyama-ds/agent-workbench/blob/11985a41d6e083eee36a8ae4fdc944058f9a0042/README.md) · [validation](https://github.com/tyama-ds/agent-workbench/blob/11985a41d6e083eee36a8ae4fdc944058f9a0042/docs/VALIDATION.md) · [research/adoption decisions](https://github.com/tyama-ds/agent-workbench/blob/11985a41d6e083eee36a8ae4fdc944058f9a0042/docs/DEVELOPMENT_LOG.md).

## Current verification
Source **11985a41d6e083eee36a8ae4fdc944058f9a0042**; tree **0ac471ac0a175f1b92e8eeebcaf4de262cb2485f**; parent **88db2ef6ac411355b93edf85864c3d9ff9a49358**; PR merge **a4088656382980894db7e671a915a96de6d6bbfc**.

Final local full suite: **1,297 passed, 42 platform-specific skips**. Dependency consistency, compilation, JavaScript syntax, whitespace and five existing synthetic state-benchmark cases pass. Independent source review passed, including 68 final focused tests. Review found a parsed-number ownership gap; raw numeric values and real input/change invalidation now cover blank/same-value/ABA edits. The 15 feature blobs and ten corrective blobs, plus every complete tree, match the reviewed local source. The exact source checkout is clean.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37402969085) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37402973289): **all five jobs passed on attempt 1** in both final-head runs. Independent review verified the source/merge checkout SHAs in all ten job logs. Each Windows matrix job reports **1,338 passed, 1 skipped**, including successful offline repeated setup, package consistency, approved-interpreter preflight and launcher gates; each Ubuntu job reports **1,297 passed, 42 skipped**.

[Final source Edge evidence](https://github.com/tyama-ds/agent-workbench/actions/runs/37402969085/artifacts/11386346864) and [PR Edge evidence](https://github.com/tyama-ds/agent-workbench/actions/runs/37402973289/artifacts/11385463544) each contain **45 checks and 118 PNGs**, zero page/CSP/external-request errors, and Edge **153.0.4234.48**. Both ZIPs passed independent API-size/digest, CRC, 120 unique flat JSON/PNG-only member and extracted-byte checks. Report source/merge and run IDs match exactly. The source ZIP is **14,330,089 bytes**, SHA-256 **813a6e20ef1d985e8f1a596a2e7b41ea06d1df2ee7d408b2e9047d6d4a533bab**. The PR ZIP is **14,354,816 bytes**, SHA-256 **72c9f5514c524b2918915e18da7868d337268874ab2bc8cbae44eff1e66811da**. Both expire **2026-10-20**.

Independent inspection accepted all nine new exact-source desktop/tablet/narrow preview, decision-control and entry screenshots; the nine corresponding PR screenshots are byte-identical. The corrected focused preview stays visible through repeated End/Home. Existing drafts, current choices, source attribution and visible controls remain intact. Hosted coverage also confirms normalized CRLF/CR/LF, stale source/draft ownership, no unintended writes and an explicit Start with the exact reviewed replacement/current-choice payload.

The [first source run](https://github.com/tyama-ds/agent-workbench/actions/runs/37401350963) on `3559294` passed all four matrix jobs but rejected a malformed compact removal fixture in Edge: it claimed loaded detail after deleting its requested agent. Independent review and failure pixels confirmed the app correctly retained its displayed source. The corrected test explicitly checks that retention, then uses a valid legacy full-state removal snapshot without relaxing production validation. Source review also corrected stale preflight guidance after polling cancels a candidate: only the retained current draft is previewed again in a visible task context. Fresh exact-head acceptance passed as recorded above.

The [second source Edge run](https://github.com/tyama-ds/agent-workbench/actions/runs/37402154387) on `88db2ef` passed all four matrix jobs and the corrected state cases, then exposed a real tablet keyboard issue: End on an already-bottom preview scrolled the dialog and hid the focused region. Independently inspected failure pixels confirmed it. Fresh candidates now reset their preview, while unmodified Home/End stay inside it and overscroll is contained. Repeated-End/Home/outer-scroll tests and strict clipping checks remain; unchanged polling preserves reading position. Final exact-head hosted checks and independent pixel review pass as recorded above.

## Historical acceptance
The [complete preceding dev26 overview](https://github.com/tyama-ds/agent-workbench/blob/11985a41d6e083eee36a8ae4fdc944058f9a0042/docs/evidence/dev26-questions-verification.md) and [exact-body manifest](https://github.com/tyama-ds/agent-workbench/blob/11985a41d6e083eee36a8ae4fdc944058f9a0042/docs/evidence/dev26-questions-verification.json) preserve **7,008 UTF-8 bytes**, SHA-256 **74a612bba38aee0411a7c1f188e3dae8fea2f3e5c68615a868cf710355af297a**, including its full verification, earlier failures/corrections and original URLs. All 18 earlier evidence payloads remain byte-identical. [Evidence index](https://github.com/tyama-ds/agent-workbench/blob/11985a41d6e083eee36a8ae4fdc944058f9a0042/docs/evidence/README.md).

## Limits
Synthetic checks do not establish corporate approval, corporate-PC/proxy compatibility, live-provider quality, GPU behavior or full accessibility conformance. No live/billable inference, local browser retry, user-PC execution, new dependency, bundled binary, merge, release or deployment. Hosted evidence retains its 14-day lifetime.
