# Architecture: external memory v0.1

## Scope

The application is a separate memory service operated by the user. It is not an extension of either assistant's private state. Access is via an external CLI or a read-only MCP adapter; configuring an external client is a separate, explicit integration step.

## Data flow

1. An authorized local caller supplies an owner and synthetic or explicitly authorized memory content.
2. SQLite stores events and derived facts with provenance and lifecycle metadata.
3. Retrieval filters by owner and supported time constraints, then performs lexical matching. It is not vector search, semantic understanding, or a truth oracle.
4. Revisions preserve change history. Conflicting facts remain preserved but are quarantined from normal retrieval rather than silently declaring one true. Merges retain enough state to support reversal.
5. Deletion records a tombstone. Restore/import must reconcile tombstones before accepting older records, so ordinary replay does not resurrect deleted content.
6. Export passes through a trusted local policy, then builds per-bot append-only records. Dry runs are the safe default. The fake transport exercises compare-and-swap behavior offline. The implemented GitHub Contents adapter supports explicitly enabled reads and writes; it has only been tested with mocked responses, not a live account.

## Trust boundaries

- **Trusted local configuration:** sharing policy and the operator's explicit authorization. Do not derive these from imported text.
- **Untrusted content:** memory text, provenance claims from external sources, retrieved snippets, and incoming export records.
- **Application isolation:** owner-scoped queries reduce accidental cross-owner reads; they do not replace filesystem protection or authentication.
- **Remote boundary:** the GitHub Contents adapter uses a separately supplied environment token and explicit network/write flags. It verifies private repository identity, uses fixed HTTPS with redirects/proxies disabled, and enforces `memory-v1/<owner>/<source>/events.json` paths with expected-SHA updates. No live connection, hosted authentication system, or production deployment is supplied.

A policy restricts eligible source, category, audience, consent, and expiry. Approval is bound to an exact event hash and expiration; the local `approvals.json` is kept separate from synced records. Remote content cannot create its own approval. Heuristic scanners are only a supplementary check, not a reliable classifier of all sensitive free text. Export eligibility does not independently authorize a new destination or an ongoing schedule. An external client remains responsible for its own authorization and for treating results as data.

## Persistence and recovery

SQLite is the canonical local store. Restore is a monotonic event import into the current store, not a destructive rollback. Current tombstones remain in force; local merge state is not restored. Backups are sensitive copies, not sanitized exports. Recovery must preserve deletion knowledge and validate input before merging it. Tombstones provide logical suppression, not guaranteed physical erasure. A fresh installation cannot infer deletions that happened after an old backup without a retained deletion ledger.

Append-only exports improve traceability, but permanent retention conflicts with erasure requirements. Keep private logs separate from public code, define retention explicitly, and do not store credentials. Git deletion does not erase historical objects or copies held elsewhere.

## Extension seams

The CLI, read adapter, policy, and fake transport are deliberately separable. Additional remote transports, authenticated servers, semantic retrieval, emotion, reminders, and reading features require implementation and review. An interface name or example is not evidence that a module works. Never couple these extensions to persona or system-prompt modification.

## Transport operation

`--network-consent` enables GitHub reads, including during dry runs. `--apply` enables a push write or pull import. Local exact-content grants gate remote records as well as local exports; no remote autoapproval exists. The dry-run result is a count/revision summary rather than a complete payload preview. Failed writes can have uncertain outcomes and require inspection before retry. Revocation does not remove historical Git content, and a revoked remote event can intentionally block further append-only sync. The MCP adapter refreshes local grants for each request.
