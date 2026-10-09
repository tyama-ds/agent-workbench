# Historical dev21 compact PR overview

This is the complete public description of draft PR #2 captured before dev23.
It applies only to source `11e3d8a0810c0a5179f3da33044874ac41d292ea`; its “Current dev21 verification” is historical.
PR last updated at capture: `2026-10-05T14:21:35Z`. No later head is accepted by this record.
The original description follows unchanged after the marker; see the adjacent JSON
manifest for its byte length, SHA-256 and original public URLs. Python-bundled work
was subsequently discontinued; these records do not authorize new bundled builds.

<!-- ORIGINAL PR BODY -->
## Scope
Stacked on draft PR #1 (`fix/orrery-inspired-cockpit`); application version **0.1.1.dev21**. This draft combines cycles 1–21 of the Windows local-first workbench. The latest cycle fixes a reachable false error after a successful completion or human question at a tool/deadline boundary. Cockpit design, native controls, permissions, runtime dependencies and prior async ownership remain unchanged.

## Current behavior
- A successful `finish_work` or `ask_user` closes its provider batch. Later calls still receive one unexecuted result each; those skipped calls cannot create a new exhaustion error. Rejected terminal calls and expiry before dispatch retain ordinary budget enforcement. No counters are refunded, skipped tools executed or expired runs reopened.
- Windows source setup retains hash-locked wheels, repeated/offline installation and CMD entrypoints. Corporate proxy/CA/mirror containment, original assignments, preflight, configured-model attribution, selected results/receipts and retained-key redaction remain in place.
- Settings saves and credential changes retain saved-revision/destination ownership. Drafts, Start/Stop responses, dialog feedback, native focus and log reading position stay with their originating context. No automatic request replay, settings merge, credential-triggered restart or history restore is added.
- File saves retain optimistic hashes, reservations and actual receipts. Queued file operations recheck deadlines; already-started saves drain. Provider completion evidence, wire replay, Local refusals and truthful tool-result closure remain covered.
- Native evaluation reports still distinguish notice-content evidence and reference-file identity from unresolved redistribution review. **Native distribution remains blocked**; this PR offers no application binary download.

Details: [README](https://github.com/tyama-ds/agent-workbench/blob/11e3d8a0810c0a5179f3da33044874ac41d292ea/README.md), [architecture](https://github.com/tyama-ds/agent-workbench/blob/11e3d8a0810c0a5179f3da33044874ac41d292ea/docs/ARCHITECTURE.md), [security](https://github.com/tyama-ds/agent-workbench/blob/11e3d8a0810c0a5179f3da33044874ac41d292ea/SECURITY.md), [validation](https://github.com/tyama-ds/agent-workbench/blob/11e3d8a0810c0a5179f3da33044874ac41d292ea/docs/VALIDATION.md), and [research/adopted/deferred decisions](https://github.com/tyama-ds/agent-workbench/blob/11e3d8a0810c0a5179f3da33044874ac41d292ea/docs/DEVELOPMENT_LOG.md).

## Current dev21 verification
Source head: **11e3d8a0810c0a5179f3da33044874ac41d292ea**. PR merge: **a07da97fb69beacb1f7023124c552bd4a58e6a3d**. Both trees: **702445f9844a5d30903b480e2dfcd1ff24aad2e0**.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37322593578) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37322603979): **all six jobs passed on attempt 1**, covering Windows/Ubuntu × Python 3.11/3.13, Windows Edge and evaluation-only packaged Windows x64. Source logs show **1200 passed, 1 skip** on both Windows versions and **1195 passed, 6 skips** on both Ubuntu versions. Repeated offline installation and CMD entrypoints passed. The PR job's actual checkout matches the named merge SHA and source tree.

Final local and independent aggregates each pass **1195 tests with 6 platform-specific skips**. The **39 new cases** comprise 30 real loopback provider-boundary cases and nine controlled/seeded session cases. These cover all three adapters, successful/rejected terminal calls, exact/exceeded boundaries, skipped writes, peer queue saturation and reserved human capacity, human/peer FIFO, Stop ordering, captured gate-waiter keys versus mailbox work, explicit recovery after errors, config ownership, accounting and cleanup. Four fixed seeds each use 40 bounded steps and independent expected state; event/task barriers determine ordering, with watchdogs only for hangs.

Independent sensitivity probes confirm the regressions reject the old terminal guard, LIFO human insertion, illegal key-triggered error restart and peer use of the reserved human slot. Dependency consistency, Python compilation, JavaScript syntax, DOM-only smoke, whitespace and historical-byte checks pass. These are bounded reachable traces, not exhaustive model checking or a liveness proof. No new UI code or design was changed, and no new pixel/accessibility claim is made.

## Fresh source-bound evidence
[Windows Edge reports/screenshots](https://github.com/tyama-ds/agent-workbench/actions/runs/37322593578/artifacts/11351190832) and [evaluation-only package reports/manifests](https://github.com/tyama-ds/agent-workbench/actions/runs/37322593578/artifacts/11349969176) bind this source head, run and dev21: **42 Edge checks**, **100 PNGs**, zero page/CSP/external errors, **11 packaged + 3 native-console checks**, **412 manifest files**, and **88 native inventory entries**. Edge version is **153.0.4234.48**. These rerun the existing UI acceptance; no new UI/pixel-review claim is made for this backend change.

Independent safe-evidence review passed. API size/digests, archive CRC and safe-member checks, every extracted byte, report source/run/version, packaged static hashes and Windows-form lock hashes were verified. The two additional manifest entries retain the exact dev20 overview/provenance. The pinned native reference retains **23 exact native-file matches** and four reviewed notice-content matches; unresolved UCRT/API-set and distribution findings remain explicit. This is evidence consistency, not legal clearance.

Evidence ZIP SHA-256: browser **c637574fb4e28651079a704d0c93c258567ca1ad602b729bd0e540f8199f26e1** (11,388,646 bytes); portable **3f06f3ea25e4a24abcd36b9fd34067abf695334dcd0d13f620542798e904d8e5** (191,242 bytes). Both expire **2026-10-19**. Only JSON/PNG evidence archives were downloaded; no application binary/distribution ZIP was uploaded or downloaded. The published checkout is clean.

## Historical acceptance and complete records
[Complete dev20 compact overview](https://github.com/tyama-ds/agent-workbench/blob/11e3d8a0810c0a5179f3da33044874ac41d292ea/docs/evidence/dev20-settings-verification.md) and [exact-body provenance](https://github.com/tyama-ds/agent-workbench/blob/11e3d8a0810c0a5179f3da33044874ac41d292ea/docs/evidence/dev20-settings-verification.json) preserve the prior public description byte-for-byte: **10,809 characters / 10,818 UTF-8 bytes**, SHA-256 **99474cd89b043f7f52328187bfe3fd8bc2689a7ced3f5ff9a7c861e6ef9bea42**. Its acceptance applies only to **b2de9a7d4c997db4f2dd01ce162e0fe427915910**.

The [versioned evidence index](https://github.com/tyama-ds/agent-workbench/blob/11e3d8a0810c0a5179f3da33044874ac41d292ea/docs/evidence/README.md) links the unchanged dev19/dev18 and frozen original records, including prior retries, run/artifact bindings, all original public links and review limits. Historical “Current verification” headings apply only to their named source heads. Earlier pixel reviews remain bound to those heads; old artifacts do not verify this revision. The original dev15 source ZIP remains unchanged.

## Blockers and limits
- **Native redistribution remains blocked.** Windows ONEDIR is unsigned, evaluation-only and NOT FOR DISTRIBUTION. Exact lxml/iconv wheel-source binding, a usable corresponding-source/relink route and remaining native component review remain unresolved; no legal clearance or source-offer commitment is implied. CI uploads JSON/PNG evidence only, never EXE/DLL/application ZIP files.
- Synthetic loopback providers, Windows CI and Edge checks do not establish live-provider quality/acceptance, company-PC/proxy compatibility or GPU behavior. No paid/live inference, user-PC work or local browser retry is included.
- No hard deadline for already-running I/O, rollback of prior saves, secure memory zeroization, arbitrary-secret detection or recall of delivered data is promised. Selected exports are not backup/restore; configured model aliases do not verify served-model identity.
- Full screen-reader/text-zoom audits remain unverified. Screenshots are human-review evidence rather than pixel baselines. No new runtime dependency, telemetry, authentication weakening, merge, release or deployment is included.
- CI evidence has 14-day retention. Recorded links and hashes can outlast downloadable bytes; evidence ZIP hashes are not application-package hashes.
