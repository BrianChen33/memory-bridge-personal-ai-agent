# Capability and limitation checklist

This describes the intended v0.1 implementation boundary. Passing local tests is evidence only for the tested behavior, not production readiness or live client compatibility.

| Area | v0.1 scope | Not claimed |
| --- | --- | --- |
| Storage | Python standard library, local SQLite, owner-scoped events and facts | Encrypted storage, multi-tenant security |
| Retrieval | Lexical matching and supported time filters | Embeddings, semantic recall, factual correctness |
| History | Provenance, revisions, conflict records | Automatic truth resolution |
| Lifecycle | Tombstones and deletion-aware replay/restore | Physical erasure of every copy |
| Merge | Reversible merge operations | Arbitrary distributed consistency |
| Recovery | Local backup/monotonic event restore; current tombstones preserved | Destructive rollback, restored local merge state, or managed disaster recovery |
| Sharing | Trusted local policy for source/category/audience/consent/expiry | Consent inferred from arbitrary imported claims |
| Export | Per-bot append-only format, dry-run default, fake CAS transport and GitHub Contents API adapter | Live-tested connection, deployment, or automatic publication |
| Muse row adapter | Pure confirmed-fact schema transformation with explicit trusted scope and exact selection | Live Muse database/CLI integration, automatic native dot hooks |
| Independent runner | Strict JSON self-test-only entrypoint with input/worker deadline and scoped cleanup | Live capture, production DB reads, automatic consent, sandbox or real-time OS guarantee |
| Client access | External CLI and read-only MCP adapter | Installed or tested native Muse/dot integration |
| Scheduling | Disabled configuration example | Installed cron job, recurring sync, autonomous reminders |
| Optional interfaces | Future extension concepts | Working emotion, reminder, or reading modules |
| Persona | No access or mutation | Persona sync, prompt edits, internal memory access |

## Before claiming a deployment works

- Run the complete local test suite and review failures.
- Inspect help/output against the actual CLI implementation.
- Test the specific external MCP client's protocol and permission behavior.
- Use synthetic data to test owner isolation, denied exports, expired consent, conflicts, merge reversal, concurrent export changes, and deletion-aware restore.
- Inspect the exact destination and payload before any real transmission.
- Live-validate the implemented GitHub adapter against an explicitly authorized private destination before claiming a working deployment; offline mocked tests are not live verification.

No real personal data belongs in fixtures, screenshots, examples, or the public code repository.

Time filtering and merge reversal are exposed by core Python APIs; the CLI and minimal MCP adapter expose a smaller command set. Content scanners are heuristic and do not replace independent review.
