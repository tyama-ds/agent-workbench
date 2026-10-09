# Documentation revision 1: internal deployment review

Historical exact public PR overview. These claims apply only to source head 59d26a962f9f03a24bf0a6f7153b635450921cf9 and its named CI runs, not later changes.

Source: https://github.com/tyama-ds/agent-workbench/pull/2
Captured: 2026-10-06T01:01:10.694Z

---

## Scope
Stacked on draft PR #1 (`fix/orrery-inspired-cockpit`). Application version remains **0.1.1.dev25**; this is **documentation revision 1**, based on verified dev25 source `497b549bec320020dd35696ab0871ef45ca832b9`. Only seven documentation/evidence files change. Application code, UI, defaults, dependencies, security behavior and the five-job CI configuration are unchanged.

## Corporate deployment handoff
- Add a 93-line Japanese [IT review checklist](https://github.com/tyama-ds/agent-workbench/blob/59d26a962f9f03a24bf0a6f7153b635450921cf9/docs/IT_REVIEW_CHECKLIST.md), with 17 blank review items, a date and an explicit behavior baseline. Link it from README and Windows setup.
- Separate approval of Python/source/dependencies, installation connectivity, runtime endpoints and data handling. Keep source-only installation and separately approved Python; no bundled runtime or automatic Python install/update.
- Cover the complete installed lock, offline wheelhouse limits, enabled initial provider profiles, mixed-team data sharing, downstream handling and independent installer/runtime proxy/CA settings.
- Include state-directory explicit-grant limits, private settings metadata, environment-key sources, retained retired-key masks, shutdown/export lifetime and the distinction between model-directed execution and fixed application helpers.
- A hash, private IP, successful setup or CI result is not corporate approval, security certification, or proof of no onward transfer. The checklist contains no filled approvals or real organization-specific information. Existing guides remain the detailed instructions.

[README](https://github.com/tyama-ds/agent-workbench/blob/59d26a962f9f03a24bf0a6f7153b635450921cf9/README.md) · [Windows setup](https://github.com/tyama-ds/agent-workbench/blob/59d26a962f9f03a24bf0a6f7153b635450921cf9/docs/WINDOWS_SETUP.md) · [security boundaries](https://github.com/tyama-ds/agent-workbench/blob/59d26a962f9f03a24bf0a6f7153b635450921cf9/SECURITY.md) · [research and decisions](https://github.com/tyama-ds/agent-workbench/blob/59d26a962f9f03a24bf0a6f7153b635450921cf9/docs/DEVELOPMENT_LOG.md).

## Current documentation verification
Source head: **59d26a962f9f03a24bf0a6f7153b635450921cf9**. Tree: **dc3c85fdab9c6aa9db5aa74646be67d268edc3ac**. Sole parent: **497b549bec320020dd35696ab0871ef45ca832b9**. PR merge: **69442879548660a571674237a516da8e0cbd534a**, with the same reviewed tree.

Final local aggregate: **1206 passed, 42 platform-specific skips**. Dependency consistency, Python compilation, JavaScript syntax and whitespace checks pass. **61 relative Markdown links/anchors** resolve. Independent source review approved the exact seven-file tree, checklist/source consistency and historical archive. All seven remote blob hashes and the complete tree match the reviewed local candidate. Optional local DOM smoke is unavailable because jsdom is absent; no dependency was installed.

Fresh [exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37395573471) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37395577073): **all five jobs passed on attempt 1** in both runs. Independent review verified actual checkout SHAs in all ten logs. The four Windows matrix logs each report **1247 passed, 1 skipped**; the four Ubuntu logs each report **1206 passed, 42 skipped**. Windows logs also confirm two completed offline installs, package consistency, explicit-interpreter preflight and actual launcher help.

[Fresh source-bound Edge evidence](https://github.com/tyama-ds/agent-workbench/actions/runs/37395573471/artifacts/11382263571) retains all **43 checks**, with **104 PNGs**, zero page/CSP/external-request errors and Edge **153.0.4234.48**. Both source and PR reports match their source/merge and run identities. The source ZIP is **11,944,954 bytes**, SHA-256 **936131f7121fcaca320e3766d8bacf5130c16776c670764596c699cbd08a60b3**, expiring **2026-10-20**. Both artifacts passed independent API-size/digest, CRC and 106 unique safe JSON/PNG-only member checks. No UI changed and no new pixel-inspection or accessibility claim is made. The published source worktree is clean.

## Historical acceptance
The [complete dev25 public overview](https://github.com/tyama-ds/agent-workbench/blob/59d26a962f9f03a24bf0a6f7153b635450921cf9/docs/evidence/dev25-setup-help-verification.md) and [exact-body provenance](https://github.com/tyama-ds/agent-workbench/blob/59d26a962f9f03a24bf0a6f7153b635450921cf9/docs/evidence/dev25-setup-help-verification.json) preserve **5158 characters / 5163 UTF-8 bytes**, SHA-256 **1f6b0a070f46c9c99775795376e03a9809fbb065bb7d1f9b9a95422e084b51f1**. All 14 preceding evidence files remain byte-identical; the [evidence index](https://github.com/tyama-ds/agent-workbench/blob/59d26a962f9f03a24bf0a6f7153b635450921cf9/docs/evidence/README.md) retains their named scope.

## Limits
Hosted CI and synthetic checks do not establish organizational approval, corporate-PC/proxy compatibility, live-provider quality, downstream retention/training behavior, GPU behavior, legal clearance or full accessibility conformance. No live/billable inference, user-PC execution, merge, release, deployment or bundled binary is included. CI reports/screenshots retain their 14-day lifetime.
