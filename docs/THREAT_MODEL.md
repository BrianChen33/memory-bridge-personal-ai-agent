# Threat model

## Assets and adversaries

Protect personal memory content, provenance, ownership, deletion intent, policy, backups, and the GitHub token and any future transport credentials. Consider malicious imported text, mistaken operators, cross-owner queries, compromised clients, stale peers, public repository exposure, and local users with filesystem access.

## Threats, controls, and residual risk

| Threat | Design response | Residual risk |
| --- | --- | --- |
| Prompt injection in a stored fact | Treat all retrieved content as data; keep policy separate | A client that executes the content can still be compromised |
| Cross-owner access | Scope application operations to owner | Filesystem/database access bypasses query filters |
| Forged source or consent | Trusted local policy; independent authorization | Self-asserted metadata is not authenticated identity |
| Oversharing to a bot or repository | Source/category/audience/consent/expiry checks; dry-run default | Operator mistakes or unsafe adapters can leak data |
| Expired authorization | Evaluate applicable expiry at the boundary | Already distributed copies cannot be recalled automatically |
| Lost concurrent export update | Compare-and-swap transport semantics | CAS does not guarantee identity, durability, or global convergence |
| Deleted facts reappear after replay | Tombstone reconciliation | Missing deletion history in a fresh restore defeats suppression |
| Mistaken merge | Reversible merge history | External actions based on the merged fact are not reversible |
| Conflicting claims become false certainty | Preserve provenance/conflicts | Consumers may still choose the wrong claim |
| Data leaked through Git history | Separate private memory from public code; no real fixtures | Private repos, clones, logs, and backups retain copies |
| Local device compromise | Restrict filesystem permissions | No built-in at-rest encryption or hardened execution sandbox |
| Automated repeated disclosure | Scheduler disabled and no native integration | Manually added jobs require separate authorization and review |

## Explicit non-goals

This prototype does not provide secure enclave storage, full audit-grade identity verification, end-to-end encryption, regulatory certification, a hosted authentication layer, guaranteed physical erasure, or native assistant interoperability. It does not inspect, synchronize, or rewrite any persona or system prompt.

## Validation priorities

Test denied-by-policy exports, owner mismatch, malformed imported data, stale CAS tokens, repeated imports, expired authorization, merge reversal, and restores after deletion. Use synthetic adversarial text, including a record claiming to override policy, and verify it remains inert. The implemented GitHub adapter has mocked offline coverage, not live verification. Review it and every future remote adapter as a separate trust boundary rather than inheriting confidence from fake-transport tests.

The GitHub adapter fixes the API host, rejects redirects/proxies, verifies private-repository identity per read/write, restricts paths, and requires explicit network and apply flags. These controls do not prevent future repository visibility changes, credential theft, or authorized collaborators copying data. Dry runs still perform remote reads. A write followed by a lost response has an uncertain outcome and must be inspected before retrying. Local revocation is not remote erasure.
