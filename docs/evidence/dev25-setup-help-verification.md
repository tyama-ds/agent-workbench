# Archived dev25 setup-help verification

This preserves the full public description of [PR #2](https://github.com/tyama-ds/agent-workbench/pull/2)
as retrieved on 2026-10-06. Its current-verification language applies only to
source `497b549bec320020dd35696ab0871ef45ca832b9` and the named runs. It is historical
evidence, not acceptance of the subsequent documentation-only IT review checklist.
Current source-only installation and separately approved Python remain required.

<!-- BEGIN ORIGINAL PUBLIC PR BODY -->
## Scope
Stacked on draft PR #1 (`fix/orrery-inspired-cockpit`); application version **0.1.1.dev25**, directly following verified source-only dev24. Existing design, corporate data-use guidance and workbench behavior remain unchanged. No unpublished dev22 changes are included.

## Setup help before Python selection
- `Setup.cmd --help`, `-h` and `/?` display fixed instructions before inspecting the approved interpreter path. Each help alias must be the first and only argument; extra arguments, including an explicitly empty quoted argument, fail without setup.
- Help runs no Python, creates no private environment, installs no packages, contacts no network and performs no prerequisite diagnosis. It prints no user environment values.
- Explain the existing temporary `WORKBENCH_PYTHON` setting, approved standard 64-bit CPython 3.11–3.13, preflight, proxy/CA and offline options. No new path selector or persistent setting is added.
- The normal wrapper body and full argument forwarding are unchanged. Separately approved Python remains required; launcher/PATH/registry discovery, bundled builds and policy bypasses remain excluded. No dependency, UI, model-routing or security-boundary change is included.
- Add 28 actual Windows cases for all help aliases and unset/missing/alias/actual/hostile selections, extra/empty arguments and normal argument/exit forwarding, plus two cross-platform checks. Existing source/Edge scenarios remain.

[README](https://github.com/tyama-ds/agent-workbench/blob/497b549bec320020dd35696ab0871ef45ca832b9/README.md) · [Windows setup](https://github.com/tyama-ds/agent-workbench/blob/497b549bec320020dd35696ab0871ef45ca832b9/docs/WINDOWS_SETUP.md) · [validation](https://github.com/tyama-ds/agent-workbench/blob/497b549bec320020dd35696ab0871ef45ca832b9/docs/VALIDATION.md) · [research and decisions](https://github.com/tyama-ds/agent-workbench/blob/497b549bec320020dd35696ab0871ef45ca832b9/docs/DEVELOPMENT_LOG.md).

## Current dev25 verification
Source head: **497b549bec320020dd35696ab0871ef45ca832b9**. Tree: **43b62fcbe9a874f8eb73fde4f17b3226a22de52a**. Sole parent: **c46bce2f508f95cf3d5a20aacc71e69b5402ab0e**. PR merge: **7dad0c1bf93aabd9a49af00d1c6f8e063442cce1**, with the same reviewed tree.

Final local aggregate: **1206 passed, 42 platform-specific skips**, repeated on the final candidate. Dependency consistency, Python compilation, JavaScript syntax and whitespace checks pass. Independent source review approved the exact tree and historical archive; all changed remote blob hashes and full-tree identity match the reviewed local commit. Local DOM-only smoke was unavailable because jsdom is absent; no dependency was installed. Actual Windows Edge CI passed.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37393860045) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37393866303): **all five jobs passed on attempt 1** in both runs. Independent review verified actual checkout SHAs in all ten logs. All four Windows matrix logs report **1247 passed, 1 skip**; all four Ubuntu logs report **1206 passed, 42 skips**. Windows logs also confirm two completed offline installs, clean package consistency, explicit-interpreter preflight and actual `Launch.cmd` help. No packaged job was created.

[Fresh source-bound Edge evidence](https://github.com/tyama-ds/agent-workbench/actions/runs/37393860045/artifacts/11382835117) retains all **43 checks**; **104 PNGs**, zero page/CSP/external-request errors, Edge **153.0.4234.48**. Both source and PR Edge reports have matching source/merge and run identities. The source-run evidence ZIP is **11,940,447 bytes**, SHA-256 **100ef338a83a84eac9ae8ba5325e1f62044c291551b9890c8ad764ce38dad928**, expires **2026-10-20**. API size/digest, CRC, 106 unique safe JSON/PNG-only members and extracted bytes were verified. No UI changed and no new pixel-inspection or accessibility claim is made. The published source worktree is clean.

## Historical acceptance
[Complete dev24 public overview](https://github.com/tyama-ds/agent-workbench/blob/497b549bec320020dd35696ab0871ef45ca832b9/docs/evidence/dev24-data-use-verification.md) and [exact-body provenance](https://github.com/tyama-ds/agent-workbench/blob/497b549bec320020dd35696ab0871ef45ca832b9/docs/evidence/dev24-data-use-verification.json) preserve **5707 characters / 5712 UTF-8 bytes**, SHA-256 **404532015d35a61d123f4718abbc144c9a274006e643e2ce11d9babc2c88ceba**. All predecessor evidence files remain byte-identical; the [evidence index](https://github.com/tyama-ds/agent-workbench/blob/497b549bec320020dd35696ab0871ef45ca832b9/docs/evidence/README.md) keeps their named scope.

## Limits
Hosted CI and synthetic loopback checks do not establish organizational approval, corporate-PC/proxy compatibility, live-provider quality, downstream retention/training behavior, GPU behavior, legal clearance or full accessibility conformance. No live/billable inference, user-PC execution, merge, release, deployment, bundled binary or source-offer commitment is included. CI reports/screenshots retain their 14-day lifetime. No new UI pixel-review claim is made.
