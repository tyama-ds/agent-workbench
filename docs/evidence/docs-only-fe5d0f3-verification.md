# Historical documentation-head verification: fe5d0f3

This preserves the explicitly scoped verification section from the compact PR
handoff for documentation-only head `fe5d0f35beebb1e951eb375289c337a0e7ca121f`.
It is historical evidence for that head, not acceptance of dev18 or later commits.
The original pre-compaction [dev17 snapshot](pr-2-2026-10-05.md) remains unchanged.
The [current native-evidence correction](../NATIVE_REDISTRIBUTION.md) clarifies the
older keyword observations without rewriting their record.

Source head: **fe5d0f35beebb1e951eb375289c337a0e7ca121f**. Tested PR merge: **8372659d6a8a7f7a01fbd2b3f88600913fc79a90**. Application version remains **0.1.1.dev17**.

[Exact-source push CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37306333838) and [PR CI](https://github.com/tyama-ds/agent-workbench/actions/runs/37306338247): **all six jobs passed in both runs** on this documentation head. Coverage is Windows/Ubuntu × Python 3.11/3.13, actual source Windows Edge, and evaluation-only packaged Windows x64. Source-push logs report **1032 passed, 1 skip** on each Windows version and **1027 passed, 6 skips** on each Ubuntu version; repeated offline setup and CMD entrypoint checks passed.

Fresh evidence: [source Edge reports/screenshots](https://github.com/tyama-ds/agent-workbench/actions/runs/37306333838/artifacts/11344250313) and [evaluation-only package reports/manifests](https://github.com/tyama-ds/agent-workbench/actions/runs/37306333838/artifacts/11344260683). Independent report/hash checks confirm **36 Edge checks**, zero page/CSP/external errors, and **11 packaged + 3 native-console checks**, bound to this source/run and dev17. The package manifest has **404 files** (three new archive documents), with **88 native entries** and unchanged blocked/unsigned/evaluation-only status. Evidence ZIP SHA-256: browser **6f6877fb75dd1fc7e9d6530514c6f9970cfa910c7da2348fa7ee3c8390108ecc**; portable **76f4e3ed463487a0a001b768a9c4ddc115bd4571d6aa964e6ec5748c416bf1bf**. Both match API digests and expire **2026-10-19**. These fresh screenshots were not independently re-reviewed as pixels; the earlier visual review below remains tied to its original source head.

Local final tree: **1027 passed, 6 platform-specific skips**; dependency consistency, compileall, JavaScript syntax, DOM-only smoke and whitespace checks passed. DOM-only checks do not establish browser layout. Source and tested-merge trees are identical: **ec0ce36cfa9697283acc5c4c42dff8e9513e099e**. The published checkout was clean at that handoff.

The changes are limited to README/documentation navigation plus the historical PR snapshot, provenance/URL manifest and cycle index. The original **63,437 characters / 63,502 UTF-8 bytes** and all **56 distinct public URLs** are preserved byte-for-byte after the snapshot marker. Independent archival review checked the original and archive body hashes, source/run/artifact associations, relative links and separation of current versus historical claims. Historical failures remain in place. Documentation-head CI does not re-date older independent screenshot reviews or imply new live-provider acceptance.
