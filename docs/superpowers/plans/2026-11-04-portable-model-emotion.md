# Portable Model Emotion Implementation Plan

**Goal:** Publish the verified model-judged emotion protocol and a self-contained replication guide, without new QQ code or private Muse data.

**Architecture:** Preserve the portable runtime and deployment wrappers. Port the emotion validator and assessment table; adapt prepare/capture, generic deployment guidance and synthetic regression tests. Host owns model calls and sender identity. No independent model API or live Muse changes.

**Tech Stack:** Python / SQLite / unittest, existing CLI and wheel packaging.

**Spec:** User-approved model emotion v1 from the existing Muse implementation; public specification in ../../SYSTEM_REPLICATION.md.

## Constraints and review focus

- No QQ bridge/hook/sticker implementation or private runtime artifacts in this sync.
- Missing/invalid is not unchanged; no keyword fallback; unchanged does not refresh at.
- First valid assessment wins; replay cannot accumulate; foreign events cannot be overwritten.
- Config damage must not be called explicit disable; reopening requires a new valid assessment.
- Assistant/article output cannot self-excite emotion; generic labels and shared projection only.
- Keep original persona guidance, bounded retrieval, legacy exchange compatibility and restore behavior.

## Steps

- [x] Add synthetic emotion protocol tests and observe failure against the old keyword implementation.
- [x] Port emotion/events changes; adapt only required brain prepare/capture blocks while preserving portable edits.
- [x] Update old automatic-keyword tests, self-test, deployment blueprint, README/API/architecture/capability and integration guidance.
- [x] Run python tools/test_all.py and python tools/check_wheel.py; inspect failures and fix.

## Verification record

14 new protocol tests observed red on the original implementation, then green.
The complete run executed 317 Python cases (2 Windows symlink capability skips)
and 7 Node cases; all available checks passed. Wheel 0.3.0 installed in an isolated
environment outside the checkout; self-test, init, enable and doctor passed.

One pre-existing quiet-boundary test mixed actual claim time with a fixed mock
morning. At the actual wall clock this produced negative lease age and busy.
Freezing both clocks in that test made the scenario deterministic; the lifecycle
implementation and its safety gates were not changed.

The public update adds generic host wording, user-only emotion changes, no QQ
trust/shared projection code, and a legacy-event replay guard for upgraded roots.
Private deployment handoff and real chat evidence are intentionally not published.
Publication follows validation; the resulting Git commit and its CI checks are
the durable publication record. The standalone guide is also delivered locally.
