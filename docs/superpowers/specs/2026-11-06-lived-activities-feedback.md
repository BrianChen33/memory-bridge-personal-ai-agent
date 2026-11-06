# Continuous activities, faster entry and feedback repair

Approved scope: the owner approved the preceding concrete proposal on 2026-11-06 and asked to fold bounded retrospective correction into the existing emotion heartbeat. Implement without another approval round, new rollback machinery or production test messages.

Preserve six layers, same-host-model full48 interpretation, one sticker decision per real round, real/virtual/dream provenance, current persona and optional channel adapters. No private production data in this repository.

## Chosen approach

Persist model-authored activity projects, with concrete topics, timed stages and native artifact text. Prepared future stages are sealed drafts, not happened events. Query-time projection exposes only reached stages. Interruption revises future stages; elapsed time alone cannot finish an unprepared artifact. Observed web reading cannot be invented. This replaces generic outcome-only simulation, without a new model on every minute or user question.

Reuse a source-bound prepared context for the same context/commit round. Commit validates the real source and saves model assessment without rerunning the whole retrieval/presentation pipeline or echoing it. Retain full48 and gate correctness.

Use the existing 15-minute emotion job for state advancement, due-event appraisals and bounded feedback checks/repairs. Use 30-minute life/news for heavier planning, drafts and discovery. Preserve reading/reminder/maintenance/backup schedules. Read real recent main-chat data with stable IDs, and select only invalid/missing assessments; successful events are immutable. Repairs use original event time, decay late effects into now, never replay old replies, re-draw stickers, or stimulate mood from the bot's own text. Unreliable source matching is reported, not guessed. Keep cursor, coverage, pending/deferred/error counts and a finite per-run budget.

## Alternatives

Adding more outcome templates leaves the missing-process defect. Running a model every minute or rereading all history before each reply adds latency. Replaying every old message would double-count emotion and send actions. The chosen approach keeps rich background data and bounded foreground reads.

## Acceptance and deployment

One final isolated acceptance pass (including tools/test_all.py and tools/check_wheel.py), targeted repair only if a failure is found. Then publish reusable code/protocol/docs/version provenance, verify remote commit, deploy via the owner's authorized Muse debug sidechat, read back native task binding and actual file hashes, update private snapshot architecture lock. No synthetic production turns or real test sends. Do not claim end-to-end latency improvement without an actual later real-turn measurement.
