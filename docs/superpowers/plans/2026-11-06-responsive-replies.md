# Responsive replies implementation plan

> Execute inline with executing-plans. Owner already approved this implementation;
> one final isolated acceptance overrides repeated per-step test cycles.

**Goal:** Reduce foreground tool orchestration and eliminate lost/duplicated reading
work while preserving pre-reply full48 appraisal and sticker idempotence.

**Architecture:** Fixed native reply driver with immutable source tickets and local
timings; optional durable reading queue with bound staged receipts; existing host
tasks split lightweight feedback from bounded browsing. No new recurring loop.

**Tech Stack:** Node ESM, Python3.10+, SQLite, existing native host tools, offline HTML.

**Spec:** ../specs/2026-11-06-responsive-replies.md

## Global constraints

- Same host reply model; complete full48 before normal text; one draw per round.
- Private original sources, IDs, task bodies and persona stay out of public code.
- Preserve settings, permissions, optional installation and existing task identities.
- No native-final/after-reply interception claims or invented tool APIs.
- One final isolated acceptance, targeted fixes only; no production probes.

## Review focus

- Ticket replay/tampering, newer owner messages, runtime upgrades and malformed input.
- Busy queue/cancel/revoked source and expired browser task ownership collisions.
- Delayed staged receipts, restart/replay and changed payload cannot duplicate emotion.
- Actual future scheduler bindings rather than guessed or already-past run times.
- Emotion job remains bounded and never browses; no loss of normal full48/draw steps.

## Tasks

- [x] 1. Add runtime/reply_driver.mjs and isolated driver regressions. Store original
  user projection once; bind commit to source ticket; reuse main_native_entry and
  sticker_main; return compact results and bounded metadata-only local timings.
- [x] 2. Add plugins/social-reading/reading_queue.py and lifecycle tests. Extend
  store initialization, plugin API/schema/panel and reader persistence for queued
  work, native binding, staged observations, honest continuation and cancellation.
  Preserve legacy plan/observe compatibility without allowing cross-job receipts.
- [x] 3. Update actual-capability host protocol, task blueprints and panel queue
  status. Keep foreground short, generate/verify one-shot future handoffs, and move
  phone browsing out of emotion15m into existing bounded background workers.
- [ ] 4. Update0.8.4/2.7.0/0.4.0 manifests, provenance, deployment and inheritance;
  independent whole-change review, one final acceptance + wheel; publish/verify,
  deploy/read back host bindings, refresh panel, lock one private snapshot.

## Ledger

2026-11-06: User approved implementation after read-only diagnosis. Existing linked
worktree clean at0adbb59; remote main matches. No separate approval loop. Preserve
current private paths, settings, task identities and native sender boundaries.

Final isolated acceptance: test_all exit0 (239+59+149 Python,13 Node); wheel exit0.
Independent review fixes: repeat-cancel ownership, cancellation/finalization eligibility,
serialized short plugin mutations, immutable ticket digest and Python runtime binding.
Targeted final verification: reading_queue9/9, reply_driver9/9, social_reading20/20.
No production probes or additional recurring task. Deployment/readback pending.
