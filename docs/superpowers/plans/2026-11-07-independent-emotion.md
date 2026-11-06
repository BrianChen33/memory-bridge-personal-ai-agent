# Independent emotion implementation plan

> Inline execution under executing-plans; owner authorized implementation and
> same-model calibration, retaining48 and no extra decision steps. One final
> isolated acceptance overrides repetitive per-step test cycles.

**Goal:** Reduce user-approval bias inside the existing emotion and reply pass.

**Architecture:** Replace two existing instruction strings. New foreground driver
returns compact48-v1 input; canonicalize to full48-v1 before unchanged signed
budgets, gain/decay, source binding, storage and once-only draw. Catalogue stays48.

**Tech Stack:** Existing Python runtime, Node reply driver and native host model.

**Spec:** ../specs/2026-11-07-independent-emotion.md

## Global constraints

- No new emotions, inference engine/model/call, extra stage or JSON fields.
- Compact input omits zero labels; legacy full input still requires exactly48.
- Real sources only; old memories/emotions never replay or reset.
- No forced negativity/label rotation/keyword rules; genuine joy remains valid.
- Preserve personal data, settings, persona appearance, growth and channel senders.
- Same-model calibration in temporary state only; no production test sends.

## Review focus

- Neutral response must remain possible without defaulting to positive labels.
- Guidance must not forbid genuine joy or prescribe irritation on routine tasks.
- Numeric delta sign is not emotional valence; caring is not necessarily joy.
- Existing comfort, mixed mood and source idempotence must not change numerically.
- Added instruction cost or purported host interception/latency guarantees.

## Tasks

- [ ] 1. Inspect bounded real appraisal records and current host persona/pointers;
  replace guidance/expression policy, add compact normalization and new-driver
  projection, retain old adapter compatibility and complete receipts.
- [ ] 2. Update canonical MODEL_EMOTION, main entry/deploy/onboarding/inheritance,
  versions/provenance/release hashes. One independent review and final isolated
  existing suite+wheel; preserve input instruction size using tokenizer proxies.
- [ ] 3. Publish and verify exact remote SHA, deploy pinned files and active policy
  snippets, same-model paired isolated calibration, refresh same panel and one
  private snapshot. Remove only owned temporary fixtures; report limitations.

## Ledger

2026-11-07: Existing linked worktree clean at25e0fb2. Chosen approach replaces
existing instructions with no inference or state-math change. Foreground instructions+template are measured with o200k_base/cl100k_base
proxies, including the compact projection; host tokenizer and latency remain unknown.
Ruling: owner later allowed simplification. Preserve48 vocabulary; compact main
input removes repetitive zeros and expands losslessly before state math. Cost:
an omitted label is now explicitly zero; main guidance must make this contract clear.

Final review: one independent read-only review found no code blockers; fixed
canonical documentation mismatches before publication.
Final acceptance: test_all first suite248, with one new Windows test-connection
cleanup error (connection context does not close SQLite). Fixed with closing();
targeted driver10/10, compact5/5. Remaining runtime208 and Node13 passed; wheel
accepted outside checkout. Two host symlink checks skipped where unsupported.
No production sends, state reset or additional model round.
