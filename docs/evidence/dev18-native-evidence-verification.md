# Historical dev18 native-evidence verification

This record preserves the prior current-verification section of draft PR #2 before
cycle 19. It applies only to source `8cfaa59ab94ae8da1e04818e0abdfc74c1b0539d`.
PR updated at capture: `2026-10-05T12:36:41Z`. It does not accept later source changes.
The section below is copied unchanged, including its retry history and review limits.

## Current dev18 verification
Source head: **8cfaa59ab94ae8da1e04818e0abdfc74c1b0539d**. Tested PR merge: **4cde9692bec6bd7512b517538820dd0233a82908**. Both trees: **020809139c1bb53c1784e66d54b1308ae569b488**.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37309228436) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37309236732): **all six jobs are green**, covering Windows/Ubuntu × Python 3.11/3.13, source Windows Edge and evaluation-only packaged Windows x64. Source test logs show **1060 passed, 1 skip** on each Windows version and **1055 passed, 6 skips** on each Ubuntu version. Repeated offline installation and CMD entrypoints passed. Local aggregate: **1055 passed, 6 platform-specific skips**, including 28 new evidence cases; 58 focused packaging/evidence tests, dependency consistency, compileall, JavaScript syntax, DOM-only smoke and whitespace checks passed.

**Retry history:** source attempt 1 had one existing native-dialog helper's Node subprocess exceed its 10-second test timeout on Windows/Python 3.13 (1059 passed, 1 failed, 1 skip), so its portable job was skipped. The sibling PR job passed. The unchanged source's failed-job retry passed in attempt 2, followed by its portable build. No production code, assertion or timeout was changed to obtain green checks. The source Edge artifact below is the successful attempt-1 evidence; the source portable artifact was produced after the retry. The original failure remains part of this record.

Evidence: [source Edge reports/screenshots](https://github.com/tyama-ds/agent-workbench/actions/runs/37309228436/artifacts/11345381705) and [evaluation-only package reports/manifests](https://github.com/tyama-ds/agent-workbench/actions/runs/37309228436/artifacts/11345223046). Reports bind this head/run/dev18: **36 Edge checks**, 77 PNGs, zero page/CSP/external errors; **11 packaged + 3 native-console checks**; **407 manifest files** and **88 native entries**. The copied reference-index hash matches source, **23 native-file identities match the reviewed official archive**, and all four reviewed notice spans match. The OpenSSL/CRT keyword flags remain false while their content evidence is correctly present. UCRT/API-set files remain explicitly unindexed and redistribution remains blocked. Independent source/notice/archive and artifact/report/hash review passed; there is no new independent pixel-review claim for these screenshots.

Evidence ZIP SHA-256: browser **1c87c6a1612b28677237c26bc7f6317b94dfe4771e133e311af17e5da4252161**; portable **22cbf7d285de9feb48877f90b4269c0e4a6fac6ca62773c67a9ec3dcbb35715b**. Both match API size/digests and expire **2026-10-19**. Only JSON/PNG artifacts were downloaded; no application binary or distribution ZIP was uploaded or downloaded. The published checkout is clean. Fresh passing checks and hash matches do not constitute legal clearance.
