# Native redistribution: evidence correction and remaining requirements

## Current policy (0.1.1.dev23)

Python-bundled prototypes, builds and distribution preparation are discontinued,
including internal evaluation. The builder, direct assembly and PyInstaller spec
reject execution; the portable CI job is removed. Python must be approved and
installed separately by the organization. The following historical engineering
record does not authorize or plan future bundled builds.

## Historical dev18 evidence (reviewed 2026-10-05)

This is an engineering record, **not legal clearance**. At dev18, portable builds
were evaluation-only and binary distribution was blocked; CI uploaded only reports,
screenshots and manifests. Those historical results retain their original scope.

## What was corrected

Cycle 5 recorded whether the copied CPython LICENSE contained exact component names.
Those flags were explicitly informational. Absence of the words `OpenSSL` or
`Microsoft CRT` did not establish absence of their license content. The exact reviewed
3.13.15 notice contains OpenSSL's Apache 2.0 text, Microsoft Distributable Code
conditions, and libffi/bzip2 notices. Their original byte spans are now indexed.
The file has mixed LF/CRLF endings; it is never rewritten or normalized by the builder.

The [frozen dev17 PR snapshot](evidence/README.md) preserves the original observations
and remains unchanged. Read this correction alongside it rather than treating a
historical keyword flag as a current compliance determination. The subsequent
[documentation-only fe5d0f3 verification](evidence/docs-only-fe5d0f3-verification.md)
is also preserved separately with its original run/artifact links and scope.

## Reviewed source and archive identities

The [Python.org 3.13.15 release page](https://www.python.org/downloads/release/python-31315/)
publishes these SHA-256 identities, independently verified during the review:

- `python-3.13.15-embed-amd64.zip`:
  `d1f04d990aee1253d8569e8e5104e30fa9f5fa830899f14843448872d936a2cf`
- `Python-3.13.15.tar.xz`:
  `1e66a7945a48390ee4c2a4268a0e4185884059a13c4aab6d148aa208deea4a76`
- The archive's 33,861-byte `LICENSE.txt`, also copied by the dev17 build:
  `62bec384df47b0328307db41455ff6ea2559e5546b394ac69148561b21703120`

The checked-in [reference index](../tools/portable-notices/cpython-3.13.15/evidence.json)
records all 28 DLL/PYD identities in that archive, four original-byte notice spans,
source-notice hashes and URLs, and the observed runtime versions. It is itself
checksum-pinned in the builder. Twenty-three dev17 native-file identities matched
that official archive, including both OpenSSL and VCRUNTIME DLLs. This is a named
historical comparison, not automatic acceptance of a later build.

The verified source archive's
[PCbuild/regen.targets](https://github.com/python/cpython/blob/v3.13.15/PCbuild/regen.targets)
lines 150–157 and 168–178 identify and concatenate license inputs.
[PCbuild/python.props](https://github.com/python/cpython/blob/v3.13.15/PCbuild/python.props)
lines 73–83 identify OpenSSL 3.0.21, zlib 1.3.1, libffi 3.4.4, bzip2 1.0.8 and XZ 5.2.5.
The official [Windows SPDX record](https://www.python.org/ftp/python/3.13.15/python-3.13.15-amd64.exe.spdx.json)
provides additional source-dependency URLs and hashes; its dependency licensing
`NOASSERTION` values are not a clearance decision.

## What each new build actually checks

The builder makes no network request for this evidence and does not execute reference
binaries. It compares already collected original notice/native bytes with a previously
reviewed reference and copies that small index alongside the notices.

1. Exact Python implementation, version, Windows platform and x64 architecture must
   match, as must recorded OpenSSL and compiled/runtime zlib observations.
2. The actual copied notice size and SHA-256, plus its inventory hash, must match.
   Each indexed component's original-byte span must match its own SHA-256.
3. Individual native paths, sizes and SHA-256 values are compared separately.
   Windows path casing is ignored; ambiguous duplicate case identities do not match.
4. Unknown versions, altered notices/files or unindexed files remain unresolved.
   A changed reference-index hash fails the evidence step and requires fresh review.

The report keeps `notice_mentions_name`, `notice_evidence` and `native_provenance`
separate. A notice-content match does not establish a mismatched binary's provenance.
`reviewed_evidence.native_files` covers only observed paths indexed in the reference
archive, not every file or embedded component. All original component review statuses,
`evaluation_only`, `distribution_status` and redistribution blockers remain unchanged.

The reference does not cover the bundled `ucrtbase.dll` or API-set forwarders; the CRT
component inventory includes them as unindexed. Their provenance and applicable
redistribution conditions still need review. Microsoft's
[redistribution guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)
and [UCRT guidance](https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment)
remain relevant; finding the CRT notice is not itself a permission determination.

## Source notices whose absence needs careful interpretation

- [CPython's zlib 1.3.1 notice](https://github.com/python/cpython-source-deps/blob/zlib-1.3.1/LICENSE)
  is not in the copied file. Its source-distribution notice requirement and optional
  product acknowledgment must not be restated as a blanket binary-notice requirement.
  This instance is separate from lxml's native zlib and its existing supplement.
- [XZ 5.2.5 COPYING](https://github.com/python/cpython-source-deps/blob/xz-5.2.5/COPYING)
  distinguishes public-domain liblzma from differently licensed command-line tools and
  build files. Missing this text does not prove a binary violation; compiler/runtime
  additions and the actual compiled sources still matter.

## lxml: substantive unresolved redistribution requirements

All seven dev17 lxml PYDs matched the exact Windows wheel
`lxml-6.1.3-cp313-cp313-win_amd64.whl`, SHA-256
`e477aca0bc0d19f3b4ae9e4f2a1cfd687c31bf772d78734910658186b40b2477`.
Its own notices, PE observations and the upstream build scripts support static iconv
inclusion. A replaceable Python extension is not evidence that its embedded iconv
uses a suitable shared-library mechanism.

The [versioned Windows dependency resolver](https://github.com/lxml/lxml/blob/lxml-6.1.3/buildlibxml.py)
selects a native release at build time. The
[2026.05.17 native release](https://github.com/lxml/libxml2-win-binaries/releases/tag/2026.05.17)
is a candidate: iconv 1.17.1, archive SHA-256
`090225898fc0b37fe1f0d3ecc3938c926de77cd7f8c3636a5c9712b61e7af849`, source submodule
`880a1fa8b5581e37e136a7b051947d3ea39097b6`, plus its versioned `libiconv.patch`.
This candidate is **not proven to be the input to the exact wheel**. Current master
has since changed and must not stand in for a corresponding-source record.

Minimum missing evidence and artifacts:

- Bind the exact wheel to native input archives, recursive submodule revisions,
  patches and build configuration.
- Supply the complete corresponding iconv source, including actual Windows changes.
- Establish an applicable source/object and build-instruction packet allowing iconv
  modification and relinking of the relevant native extensions, or another applicable
  licensed route. A loose upstream-source URL or license file is insufficient evidence.
- Review notices, distribution terms and required modification/reverse-engineering
  permissions before any decision to distribute.

The existing [LGPL 2.1 text](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt) was
retrieved from GNU and exactly matches the unchanged checked-in supplement hash.
Its section 6 describes the relevant alternatives; possession of the text alone does
not satisfy or establish source/relinking compliance. If the existing wheel's exact
packet cannot be established, a separately approved, fixed-source native rebuild and
replacement/relink test is a feasible next engineering project. This revision does
not rebuild dependencies, substitute libraries, drop Office features, promise a
source offer, accept an agreement, or authorize distribution.
