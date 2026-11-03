# Portable deployment implementation plan

> Required workflow: execute inline (superpowers:executing-plans); one fresh
> whole-branch review. User directly authorized repository repair/public README.

Goal: make this repository contain the complete discussed runtime and a tested
entrypoint another compatible personal bot can deploy.
Spec: ../specs/2026-11-03-portable-deployment.md

1. Pin baseline033d739 and run existing88 tests; document Windows symlink-only
   limitation. Add public-source provenance map and vendor verified runtime and
   its194tests under personal_bot/runtime, keeping old memory_bridge intact.
2. RED→GREEN tests for external-root init idempotence, no persona/old-path copy,
   real prepare emotion/time path, feature flags, full backup+isolated restore,
   native schedule blueprint (disabled and real executable commands), feature
   pause rollback preserving DB, model/due-guard wrappers, wheel installation.
   Implement personal_bot/deploy.py and CLI with explicit paths and no hidden
   automatic network/install/notification side effects.
3. Write README and host adapter/architecture/acceptance/rollback docs; give a
   copyable deploy request, capability checks, source IDs, truthful scheduling and
   resource boundaries, lifecycle preservation and opt-in legacy sync. Add CI.
4. Full regressions, installed-wheel CLI walkthrough, optional real pinned model
   check and readback; final fresh code review, one tested fix pass; audit tracked
   source for private data and VM-specific paths; publish via atomic expected-SHA
   GitHub update. Verify remote tree/files/commit. Preserve local repair branch.
