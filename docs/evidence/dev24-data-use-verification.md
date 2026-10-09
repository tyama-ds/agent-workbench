# Archived dev24 data-use-guidance verification

This preserves the full public description of [PR #2](https://github.com/tyama-ds/agent-workbench/pull/2)
as retrieved on 2026-10-06. Its current-verification language applies only to
source `c46bce2f508f95cf3d5a20aacc71e69b5402ab0e` and the named runs. It is historical
evidence, not acceptance of the subsequent setup-help change. Current source-only
installation and separately approved Python remain required.

<!-- BEGIN ORIGINAL PUBLIC PR BODY -->
## Scope
Stacked on draft PR #1 (`fix/orrery-inspired-cockpit`); application version **0.1.1.dev24**, based directly on verified source-only dev23. Existing workbench behavior and design are retained. No unpublished dev22 changes are included.

## Data-use clarity
- Add one in-place readiness paragraph distinguishing LOCAL APP from model inference location. Local accepts this PC or private-LAN APIs and may reach another PC; teammate messages may share content with other selected model endpoints.
- Ask users to check **every PM/worker endpoint, proxy and downstream retention, forwarding and training use** against organizational requirements. The app does not verify organizational approval or downstream handling.
- Correct README/SECURITY wording: permitted file-tool content enters model conversations, but a file-read permission is not described as organizational authorization. Local-only plus Web-off does not guarantee no onward transfer.
- Existing prompt/file/tool-result, search-query/fetch-URL, endpoint, proxy and file-scope explanations remain. No network probe, routing/policy change, telemetry, persistence, new settings control or runtime dependency is added.
- Repeat Local-only/mixed readiness previews and retain native focus, drafts, wrapping and reachable controls at desktop/narrow sizes. All previous browser scenarios remain.

## Source-only installation remains
Python must be separately approved and installed. Setup requires the explicit actual interpreter path through `WORKBENCH_PYTHON`; bundled prototypes/builds/distribution and portable CI remain discontinued. Existing hash-locked source installation, approved proxy/CA/mirror handling and repeated/offline setup are unchanged.

[README](https://github.com/tyama-ds/agent-workbench/blob/c46bce2f508f95cf3d5a20aacc71e69b5402ab0e/README.md) · [Windows setup](https://github.com/tyama-ds/agent-workbench/blob/c46bce2f508f95cf3d5a20aacc71e69b5402ab0e/docs/WINDOWS_SETUP.md) · [validation](https://github.com/tyama-ds/agent-workbench/blob/c46bce2f508f95cf3d5a20aacc71e69b5402ab0e/docs/VALIDATION.md) · [development decisions](https://github.com/tyama-ds/agent-workbench/blob/c46bce2f508f95cf3d5a20aacc71e69b5402ab0e/docs/DEVELOPMENT_LOG.md) · [security boundaries](https://github.com/tyama-ds/agent-workbench/blob/c46bce2f508f95cf3d5a20aacc71e69b5402ab0e/SECURITY.md).

## Current dev24 verification
Source head: **c46bce2f508f95cf3d5a20aacc71e69b5402ab0e**. Tree: **1cf7ebcfd7450f6fbf9caeb3efb6a8288e25384b**. Parent: **cd8cbd77d358d2a2866cf56be41099e189bdb461**. PR merge: **0b94ccfff16e5ca8fc6d1b5651e0471b6aa886cb**, with the same reviewed tree.

Final local and independent aggregates: **1204 passed, 14 platform-specific skips**. Dependency consistency, Python compilation, JavaScript syntax and whitespace checks pass. Independent source review approved the exact tree; all remote file blob and tree hashes match the reviewed local commit.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37392210567) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37392216604): **all five jobs passed on attempt 1**. Windows/Ubuntu × Python 3.11/3.13 and Windows Edge ran; no packaged job was created. All four Windows matrix jobs report **1217 passed, 1 skip**; all four Ubuntu jobs report **1204 passed, 14 skips**. Actual checkout SHAs were verified in all ten job logs. Windows logs confirm repeated offline setup, package consistency, explicit interpreter preflight and the real launcher.

[Fresh source-bound Edge evidence](https://github.com/tyama-ds/agent-workbench/actions/runs/37392210567/artifacts/11381483619): **43 checks**, retaining all **42** prior checks; **104 PNGs**, zero page/CSP/external-request errors, Edge **153.0.4234.48**. Independent review inspected **21 images**: all four new data-use screenshots, both readiness screenshots and all 15 existing first-task desktop/tablet/narrow screenshots. Text wraps completely, native controls remain reachable/unobscured, focus is visible and original disclosures/forms are intact. This is targeted pixel review, not a full accessibility audit.

Evidence ZIP: **11,933,567 bytes**, SHA-256 **edc0beac79c8f26ec493e8a597cbdb766c001137d58b565ccd29929ad9fcfce4**, expires **2026-10-20**. API size/digest, ZIP CRC, 106 unique safe JSON/PNG members, extracted bytes and report source/run identities were independently verified. No application binary is built, uploaded or downloaded. The published source worktree is clean.

## Historical acceptance
[Complete dev23 public overview](https://github.com/tyama-ds/agent-workbench/blob/c46bce2f508f95cf3d5a20aacc71e69b5402ab0e/docs/evidence/dev23-source-only-verification.md) and [exact-body provenance](https://github.com/tyama-ds/agent-workbench/blob/c46bce2f508f95cf3d5a20aacc71e69b5402ab0e/docs/evidence/dev23-source-only-verification.json) preserve its original description: **5655 characters / 5668 UTF-8 bytes**, SHA-256 **ba8cefa1dc30b949c6c745bdab4d67ffd4b234bd234f589d71a1bc7260d7c785**. All predecessor evidence files remain byte-identical; the [evidence index](https://github.com/tyama-ds/agent-workbench/blob/c46bce2f508f95cf3d5a20aacc71e69b5402ab0e/docs/evidence/README.md) keeps their named scope.

## Limits
Hosted CI and synthetic loopback checks do not establish organizational approval, live-provider quality, corporate-PC/proxy compatibility, downstream retention/training behavior, GPU behavior, legal clearance or full accessibility conformance. No live/billable inference or user-PC execution is performed. No merge, release, deployment, bundled binary or source-offer commitment is included. CI reports/screenshots retain their 14-day lifetime.
