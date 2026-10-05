# Security model

This application gives model-generated instructions a deliberately small set of tools. It is not a replacement for Windows account isolation, a VM, a network firewall, or an inference-server allocator.

## Enforced boundaries

- Only the human-facing settings API can change provider profiles, budgets, or folder scope. Models cannot change settings, load plugins, execute shell commands, install packages, or launch processes. The GPU monitor runs a fixed `nvidia-smi` query from a trusted executable location; there is no model-controlled subprocess command.
- All model-directed file operations use the same harness. Read and write roots are independent; deny wins. Empty roots deny all. Paths with traversal, Windows devices, alternate streams, UNC, symlinks, junctions, reparse points, or hard links are rejected. The application and state directories are always denied, including when a containing directory is allowed.
- File tools are serialized across teams. Reservations prevent other agents from operating on a reserved range. Writes compare the expected SHA-256, use bounded temporary files, and replace atomically. Windows parent directory handles resist rename/delete during file operations. This does not promise protection against every malicious same-user filesystem race or an external editor ignoring reservations.
- Text reads/search require strict UTF-8 without NUL bytes. Text mutations additionally reject known PDF/Office/OpenDocument, image, archive and WAV/AVI suffixes (including new or empty targets), known document/container signatures even under another extension, and C0 controls other than TAB/CR/LF plus DEL/C1 controls. Both output and the locked existing hash-check snapshot are validated, including write-only folders. Patches preserve an existing BOM. This is conservative protection, not exhaustive binary/MIME detection. Ordinary empty UTF-8 text, CSV/JSON/SVG and BOM remain supported. Use the separate package-validated Office tools; PDF editing is unsupported. Keep valuable originals read-only.
- ZIP expansion, XML, external relationships, macro packages, DDE fields, and formula behavior are checked before supported Office processing. This is a constrained document editor, not a complete Office malware scanner. Unknown complex packages can be rejected.
- Only PM can spawn workers. The worker count is bounded for the life of a run, and mail recipients must belong to that run. A separate automatic collaboration budget (default 24) counts successful worker assignments, peer mail and automatic completion/error delivery; exhausted budgets cannot be reset by agent text or a human follow-up. Pending mail and history have bounds. Model/tool/turn/context/output/time budgets stop repeated work. The currently running file operation is drained before a stopped team releases its lock and reservations.
- A successful `ask_user` or `finish_work` suppresses every later tool in the same model response. Every suppressed or budget-exhausted call receives a result so API history remains well formed. Peer mail cannot clear a human question. Human replies keep FIFO order and precede queued peer mail.
- UI/server bind exclusively to loopback. A random, one-use, 180-second fragment bootstrap token creates an HttpOnly SameSite=Strict session cookie. Host, Origin, Fetch-Site and JSON checks protect state-changing requests. No permissive CORS. Browser assets are local; untrusted text is rendered as text, with CSP and no HTML execution sinks.
- Local API traffic ignores environment and configured proxies. Cloud APIs use only explicit profile proxies. No model-controlled provider or proxy URL. Redirects from provider calls are refused to avoid forwarding credentials.
- Web search and page fetching use the explicit search proxy or explicit direct mode, never environment proxy fallback. Public page fetch validates and pins resolved public IPs, keeping the original Host and TLS identity; redirects are revalidated. Link-local, private, loopback, metadata, IPv4-mapped and transition addresses are rejected. Only the human-configured SearXNG search origin is allowed to be internal; HTTPS is required even on LAN, except HTTP at localhost/127.0.0.1/[::1]. Proxy connections may observe requested data; use a trusted proxy.

Web-text decoding uses a fixed standard-library codec allowlist and strict errors, never arbitrary remote codec names, replacement fallback or statistical detection. Charset declarations can select only a decoder, not execute code. BOM/header precedence is separate from bounded conservative HTML-meta/XML-declaration inspection. The decoder does not resolve XML entities or DTDs. Errors omit response bytes and untrusted labels. UTF-32, contradictory ASCII XML UTF-16 declarations and NUL-bearing UTF-8 defaults/JSON are rejected. Declared encodings and well-formed decoded text do not certify the source's accuracy or safety. Network limits and destination validation are unchanged.

## Prompt and data trust

The default shared system policy is visible and editable. The runtime appends the verified agent ID, role, parent, allowed profiles, worker limit, and selected folder scope. Tool descriptions are in source. There are no hidden network-fetched prompts, scheduled commands, update checks, analytics, remote plugin loading, or mandatory external orchestration services.

Incoming file text, web text and teammate messages are untrusted data. Labeling them does not guarantee that a model will ignore all prompt injections. The enforced tool boundaries remain necessary. An attacker who controls a permitted file can still influence the quality of the model's answer or cause unwanted edits **within** allowed write roots.

Reading a file authorizes its content to enter the selected model conversation. Team mail may move content from a Local worker into a cloud PM. Search queries and URLs can also carry content. There is no per-document data-loss-prevention classifier. Use Local-only teams with Web disabled when external transfer is prohibited; do not include unrelated secrets in permitted roots. Filename/role labels and error messages are not confidentiality boundaries.

## Credentials and state

API keys come from explicitly named environment variables or memory-only input. The dedicated credential fields are not returned by the settings API or written into settings/log files. Public settings remain editable metadata: labels, models, endpoints, paths and policy are returned and persisted as entered, so never paste credentials into those fields. Provider error bodies are not displayed.

State snapshots (full and selected), logs, results, save receipts, diagnostics and application errors mask exact configured credential values recognized by the running engine. A private output-only registry keeps recognized current and retired values while run histories remain in that process, so deleting a reference, replacing a key, a late response or continuing an old conversation cannot reveal an already recognized value. Registry values are never an authentication source, public response field, export or persistent store. Copy/export uses the public records it received; export attribution receives the same masking.

The registry accepts at most 512 distinct nonempty values and 2 MiB of their combined UTF-8 payload. These are payload bounds, not a total Python-memory limit. It never evicts a mask while retained histories exist. A supported key/config change that would exceed either bound is rejected before changing credentials or the settings file; existing settings and masks remain in effect. Save needed work and restart the app before configuring more values. Unexpected in-process mutation beyond these bounds prevents new public projections and credential-bearing provider/search/diagnostic requests from proceeding, using fixed safe error text rather than an unredacted fallback. Matching uses literal searches with at most one pending match per value, not user-controlled regex patterns or an expanding character trie.

Retired values increase sensitive process-memory retention until the engine and its histories are discarded, normally when the app exits. Python cannot promise immediate secure zeroization; same-user process inspection remains outside this boundary. This is exact-value masking, not a detector for arbitrary sensitive data, substrings/fragments, encodings or transformed secrets. Private model conversations, protocol payloads and workspace file contents are not rewritten. Previously delivered browser data, clipboard contents or downloaded files cannot be recalled when a value later becomes a credential. Editable settings metadata is likewise outside this projection guarantee.

New provider/search requests resolve current credentials. An already dispatched request retains its original headers; replacement cannot retract it. Removing a provider or changing its kind, endpoint or environment-key reference clears that profile's memory credential. Changing the search provider, endpoint or environment-key reference clears the search memory credential. Re-enter a key for the new identity, or use its explicitly configured environment source; label/model-only changes preserve credentials. Profile ID `search` is reserved for search credentials. Older manually authored configurations using that ID must rename it before starting this version.

Settings contain paths, endpoint/model names and the shared policy; they are private metadata even without keys. State directory permissions remove inherited access on Windows and grant the current user/SYSTEM. Existing explicit grants on a manually selected state directory are not automatically revoked; use the new default application state folder. A process running as the same Windows user can still inspect memory or modify files. Do not run this application as Administrator or expose the UI via a reverse proxy.

Conversation and run state are in memory only. A browser session cookie is a bearer credential for the local app. Initial launch URLs should not be shared. `--no-browser` prints a short-lived launch URL to the console intentionally. API cancellation closes the client request; it cannot promise that the upstream server stopped generation or billing.

## Resource limits

Local concurrency and admission intervals are process-wide. GPU readings cover a selected **whole local NVIDIA GPU**, including other processes. A successful preflight check does not reserve memory; model loading and KV cache growth can exceed the threshold after admission. Remote GPU monitoring and hard per-process VRAM caps are not provided. Configure hard limits in the inference server or a suitable runtime.

Multiple independently launched Workbench servers have independent budgets; the limits do not coordinate across machines or server processes. Monetary billing is not calculated. Per-request output tokens and per-run call limits provide a bound on application requests, not an exact price cap.

## Reporting

Do not put real API keys, private documents, prompts or launch URLs in a public issue. Report reproduction steps using synthetic data. Tests under `tests/` contain fake keys and local API fixtures, not live credentials. See `docs/VALIDATION.md` for what was and was not exercised.

## Saved-target credential recovery

Every browser `POST /api/secrets`, including clearing a memory override, requires
an exact integer `config_revision` obtained with the saved configuration. Missing,
malformed or stale revisions fail before changing credentials or the redaction
registry. The process-local revision advances only after successful configuration
persistence, never after key replacement. It is neither persisted configuration nor
a run-eligibility value. Revision and target checks occur after the request body is
read, with no await before the existing atomic secret setter. Existing session,
Host/Origin, JSON and capacity checks remain mandatory; the revision is a concurrency
precondition, not an authentication credential or a replacement for authorization.

Saved provider IDs bind memory keys. Search uses its separate reserved identity;
nonempty search submissions require saved Brave settings with an explicit endpoint.
The UI discloses saved identity, endpoint and proxy. Dirty/new settings cannot receive
keys, and active runs never unlock configuration. The read-only discard/reload action
preserves unrelated task and conversation drafts. Concurrent key operations have
per-target ownership and prevent configuration writes until they settle.

Replacement affects subsequent ordinary requests for that profile/search identity
across all teams in this process. It does not alter dispatched headers, verify an API
key, enqueue a retry, refill quotas or restart stopped work. Explicit human messages
still pass the original eligibility checks. Late responses cannot repaint reopened
or rebound credential fields. Unknown outcomes are not automatically replayed;
credential-presence booleans cannot establish which key is currently installed.
Input values are cleared on submit, dismissal and configuration editing; JavaScript
and Python do not promise secure zeroization of previously allocated strings.
