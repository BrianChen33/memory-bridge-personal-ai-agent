# Humor and emotion gain implementation plan

> For agentic workers: execute inline with superpowers:executing-plans.

**Goal:** Ship the approved evolving meme/banter system and emotion reaction gain in Muse and the portable kit.
**Architecture:** Scoped SQLite knowledge sidecar tables, one canonical settings record, same reply model, bounded offline context, official read-only background sync.
**Tech Stack:** Python stdlib/SQLite, existing Node host adapter, single-file HTML.
**Spec:** ../specs/2026-11-05-humor-and-emotion-gain.md

## Global constraints

User-authorized implementation; default banter level 50; preserve high-band copy;
counterattack independent; emotion gain default 1.0/range 0–3; no new model or
rollback; private data stays private; one final isolated acceptance, no real sends.

## Review focus

Cross-scope learning/feedback, retries after changing gain/config, saturation and
gain zero, public detail envelope/pagination failures, offline panel truthfulness.

## Tasks and ledger

- [x] 1. Add humor.py settings/context, meme_store.py scoped learning/audit, meme_sync.py public seed/sync. Add isolated tests covering the review focus.
- [x] 2. Wire companion initialization/prepare, signed gain with original/effective audit and replay, main adapter passthrough, panel and generic task blueprints. Update deployment/API/model/learning/inheritance docs and provenance for release 0.6.0.
- [ ] 3. Run python tools/test_all.py and python tools/check_wheel.py as one final isolated acceptance; fix only concrete failures. Review, publish and verify remote commit.
- [ ] 4. Install exact published whitelist into Muse, connect actual model fields and learning/settings instructions, register/read back daily/weekly sync, refresh panel and private architecture lock. Report observed capabilities and native-hook limitation.

Ruling: user and AGENTS explicitly replace per-task TDD/full-suite loops with one
final isolated acceptance. Existing clean code checkout is preserved; implementation
uses a dedicated linked worktree/branch. Approval was given in the chat; no
additional planning approval or rollback feature is required.

Final acceptance: initial root run137 tests exposed a candidate origin field collision and test-helper naming; repaired with the focused humor suite. Remaining runtime208 and Node11 passed; verified the6696-record pinned seed in disposable state. One fresh read-only review found current-interpretation evidence, preference replay, and style-disable bypass issues; fixed with focused18/18 checks. Wheel0.6.0 installed outside checkout, new modules/settings/panel/CLI passed and synthetic state was removed. No production probes. Public sync/real installation remain task3/4 until verified.
