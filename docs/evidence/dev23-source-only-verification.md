# Historical dev23 compact PR overview

This is the complete public description of draft PR #2 captured before dev24.
It applies only to source `cd8cbd77d358d2a2866cf56be41099e189bdb461`; its “Current dev23 verification” is historical.
PR last updated at capture: `2026-10-05T23:52:55Z`. No later head is accepted by this record.
The original description follows unchanged after the marker; see the adjacent JSON
manifest for its byte length, SHA-256 and original public URLs. Source-only installation
and separately approved Python remain the current requirement.

<!-- ORIGINAL PR BODY -->
## Scope
Stacked on draft PR #1 (`fix/orrery-inspired-cockpit`); application version **0.1.1.dev23**, based directly on verified dev21. Existing workbench behavior from cycles 1–21 is retained. This change aligns installation with the requirement that Python is approved and installed separately by the organization. No unpublished dev22 changes are included.

## Source-only installation
- **Python-bundled prototypes, builds and distribution preparation are discontinued**, including evaluation-only builds. The former builder CLI, direct assembly API and PyInstaller spec stop before any download/build operation. The portable CI job is removed.
- Setup requires the full local path to the actual approved standard CPython 3.11–3.13 64-bit installation through `WORKBENCH_PYTHON`; the optional PowerShell wrapper also accepts `-PythonExecutable`. It does not invoke install-capable `py` / `python` aliases to discover a runtime.
- A standard interpreter layout is checked before execution. This checks files, not organizational approval. Missing/alias-like paths stop with instructions; Python is never downloaded or installed by the application. Launch continues through the source installation’s private environment.
- Hash-locked dependency wheels, approved proxy/CA/mirror handling, repeated/offline install checks and existing application behavior are retained. No machine policy, registry, global PATH or persistent environment setting is changed.
- Old notice helpers, lock and acceptance records remain historical/inactive. Their former evaluation or redistribution status does not authorize new bundled work.

[README](https://github.com/tyama-ds/agent-workbench/blob/cd8cbd77d358d2a2866cf56be41099e189bdb461/README.md) · [Windows setup](https://github.com/tyama-ds/agent-workbench/blob/cd8cbd77d358d2a2866cf56be41099e189bdb461/docs/WINDOWS_SETUP.md) · [validation](https://github.com/tyama-ds/agent-workbench/blob/cd8cbd77d358d2a2866cf56be41099e189bdb461/docs/VALIDATION.md) · [development decisions](https://github.com/tyama-ds/agent-workbench/blob/cd8cbd77d358d2a2866cf56be41099e189bdb461/docs/DEVELOPMENT_LOG.md) · [security boundaries](https://github.com/tyama-ds/agent-workbench/blob/cd8cbd77d358d2a2866cf56be41099e189bdb461/SECURITY.md).

## Current dev23 verification
Source head: **cd8cbd77d358d2a2866cf56be41099e189bdb461**. Tree: **75140928a67543fcbae6b3e93256f37bc6b40563**. Parent: **11e3d8a0810c0a5179f3da33044874ac41d292ea**. PR merge: **a3931a3060346bfd90491856e745ac9e05557b18**, with the same reviewed tree.

Final local and independent aggregates: **1202 passed, 14 platform-specific skips**. Focused source-only/installer/historical-helper checks: **151 passed, 10 Windows skips**. Dependency consistency, Python compilation, JavaScript syntax, whitespace, disabled-entrypoint inspection and historical-byte checks pass. Independent code review is bound to this exact tree.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37390418046) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37390425326): **all five jobs passed on attempt 1**. Windows/Ubuntu × Python 3.11/3.13 plus Windows Edge ran; no packaged job was created. All four Windows jobs report **1215 passed, 1 skip**; all four Ubuntu jobs report **1202 passed, 14 skips**. Windows tests cover the eight new missing/alias-runtime rejection cases and the compatibility wrapper under the runner’s existing execution policy. Logs confirm repeated offline setup, package consistency, explicit `WORKBENCH_PYTHON` preflight and actual `Launch.cmd` help. Independent review verified actual source and PR-merge checkouts and their matching trees.

[Fresh source-bound Edge evidence](https://github.com/tyama-ds/agent-workbench/actions/runs/37390418046/artifacts/11380952581): **42 checks**, **100 PNGs**, zero page/CSP/external-request errors, Edge **153.0.4234.48**. Report source and run identities match the source CI. API size/digest, ZIP CRC, unique safe members and JSON/PNG-only contents were verified. There is no new UI or pixel-review claim.

Evidence ZIP: **11,398,476 bytes**, SHA-256 **0178283039a2c302c74e9c6bf49836392ba7a2753951e5fc7c143f2a47433b17**, expires **2026-10-19**. This contains reports/screenshots only; no application binary is built, uploaded or downloaded. The published source worktree is clean.

## Historical acceptance
[Complete dev21 public overview](https://github.com/tyama-ds/agent-workbench/blob/cd8cbd77d358d2a2866cf56be41099e189bdb461/docs/evidence/dev21-transitions-verification.md) and [exact-body provenance](https://github.com/tyama-ds/agent-workbench/blob/cd8cbd77d358d2a2866cf56be41099e189bdb461/docs/evidence/dev21-transitions-verification.json) preserve its full original description: **8403 characters / 8410 UTF-8 bytes**, SHA-256 **66a39fe54c5212c4b713dc5482e9dad0a09d57565b01081255d49aec186a6f9a**. Its six-job/package evidence applies only to dev21. Earlier records and notice bytes remain unchanged; the [evidence index](https://github.com/tyama-ds/agent-workbench/blob/cd8cbd77d358d2a2866cf56be41099e189bdb461/docs/evidence/README.md) identifies each named scope.

## Limits
Hosted CI and synthetic loopback tests do not establish live-provider quality, corporate-PC/proxy compatibility, organizational approval, GPU behavior, legal clearance or a full accessibility audit. No live/billable inference or user-PC execution was performed. Runtime dependencies and application security boundaries are unchanged. No merge, release, deployment, Python-bundled artifact or source-offer commitment is included. CI reports/screenshots retain the existing 14-day lifetime.
