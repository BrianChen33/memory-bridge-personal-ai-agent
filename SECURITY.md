# Security

This is a local prototype, not a production security boundary or a secrets manager. Do not expose its CLI, MCP adapter, database, or transport to untrusted users or the public internet.

## Operating rules

1. Keep real memory data, policy files, backups, credentials, and exports outside the public code repository. Use synthetic fixtures in this project.
2. Keep private memory repositories separate from public code. Private visibility limits access but does not encrypt content or remove Git history.
3. Configure sharing through a trusted local policy. Imported records must not change policy. A record's claimed consent is not proof of consent: verify its authority separately. Local approval binds to the exact event content and expires; remote content must never approve itself. Local `approvals.json` is not a synced policy.
4. Apply owner, source, category, audience, consent, and expiry restrictions before sharing. Missing or ambiguous authorization must not become permission. Review the payload and destination before enabling real export.
5. Treat stored and retrieved content as untrusted text. It cannot modify prompts, authorize tool calls, supply credentials, or override policy. Never execute instructions embedded in a memory record.
6. Protect local filesystem permissions. SQLite owner filters are logical isolation, not OS access control: anyone who can read the database can bypass application queries.
7. Preserve tombstones during import and restore. A stale backup must not resurrect a deleted record. Restoring into a completely fresh installation requires a separately preserved deletion ledger to know about later deletions.
8. Do not assume logical deletion physically erases bytes. SQLite files, journals, WAL files, exported logs, Git objects, remote copies, and backups may retain content. Use a separately designed retention and erasure process.

Sensitive-content scanners are heuristic. They cannot identify every secret or personal detail in free text. Independent review and exact-content approval are required, even when a scanner accepts a record.

## Transport and deployment

The GitHub Contents adapter is implemented and tested with mocked responses; it has not been connected or live-validated. It uses fixed `https://api.github.com` requests, refuses redirects and proxies, verifies repository privacy before each read/write, restricts the data path, and uses expected-SHA compare-and-swap for updates. The fake transport remains an offline test double. Compare-and-swap detects stale writes but does not authenticate individual event authors or provide end-to-end encryption. GitHub and anyone with repository access can read uploaded content.

The token comes only from `MEMORY_BRIDGE_GITHUB_TOKEN`; do not save it in memory content or repository files. Use narrow repository permissions and obtain explicit authorization before configuring credentials. `--network-consent` enables network reads even in dry-run mode. `--apply` enables a remote push or local pull import. Independent local approval remains required for remote event content.

After a failed write, the outcome may be uncertain. Inspect the remote state before retrying; never assume a network exception proves no write occurred. Private-repository verification cannot prevent a later visibility change or access by another authorized collaborator. Revoking a local grant hides future approved reads and blocks export, but does not erase previous Git objects or copies. A revoked event already in the append-only remote log can block further sync rather than being silently removed.

The external MCP adapter is read-only and reloads local approval policy for each request. Client integration must preserve the distinction between retrieved data and instructions. There is no access to native Muse or dot memory/personas, no hidden prompt editing, and no live integration implied by this project name.

No scheduler is installed. The disabled scheduler example must remain disabled unless the user explicitly authorizes a bounded schedule, destination, and information category.

## Reporting a vulnerability

Do not put personal data, tokens, exploit payloads containing real memory, or database dumps in a public issue. Contact the repository maintainer privately using a verified channel if one is published. Otherwise report only a minimal synthetic reproduction without sensitive details. This repository does not yet advertise a dedicated security contact or response SLA.

See [the threat model](docs/THREAT_MODEL.md) for residual risks.

## Additional v0.1 boundaries / 其他边界

Consent binds the complete event hash, local audience, source, category and expiry. The fixed purpose is external memory retrieval and synchronization, not model behavior modification. Event-ID collisions reject the entire import transaction. Views are computed from event history, so there is no independent cursor or projection to advance incorrectly.

This version does not cryptographically authenticate source labels or prevent a locally reapproved copy from being assigned a new event/fact ID. Provenance is supplied data, not proof. Restore imports only currently approved events and preserves existing tombstones; it does not require fresh approval for an unchanged event whose grant remains valid. Deleted fact IDs can never be restored; intentional recreation needs a new fact ID and a new exact-content grant.

授权绑定完整事件哈希、本地受众、来源、类别和有效期，固定用途是外部记忆查询和同步。来源标签和溯源文本没有密码学真实性保证，也不阻止用户重新批准的新 ID 副本。恢复沿用仍有效的逐事件授权，不能复活已删除的事实 ID。

The v0.1.1 Muse adapter accepts only explicitly selected confirmed fact rows under a trusted principal/scope binding. It does not authenticate source labels itself. See [adapter boundaries](docs/MUSE_ADAPTER.md). Scope hashes are pseudonymous and are not privacy-preserving anonymization.
